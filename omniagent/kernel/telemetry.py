"""Lightweight tracing: one span per graph node, masked inputs.

Not a full OpenTelemetry integration (no collector is configured anywhere
in this project) but a real, minimal span recorder that captures exactly
what "every turn's trace carries masked inputs" asks for: a name, timing,
and a masked snapshot of whatever inputs mattered, per node, per turn.
Swapping this for real OTel spans later is a matter of where a finished
`Trace`'s spans get sent, not how spans get created or masked.

Masking here is deliberately narrow and pattern-based (emails, long digit
runs that look like phone numbers or card numbers) rather than reusing
`kernel/gates/pii_mask.py`'s column-based masking, since that gate masks
declared PII *columns* in a result table; this masks arbitrary free-text
*inputs* (a raw question, a filter value) where there is no schema to
consult, only the text itself.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from langgraph.errors import GraphInterrupt

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LONG_DIGIT_RUN_RE = re.compile(r"\b\d{9,}\b")


def mask_value(value: Any) -> Any:
    """Mask email addresses and long digit runs (phone/card-like) in a
    value, recursing into dicts, lists, and tuples. Non-string leaves
    (numbers, booleans, None) pass through unchanged."""
    if isinstance(value, str):
        masked = _EMAIL_RE.sub("***@***", value)
        return _LONG_DIGIT_RUN_RE.sub("***", masked)
    if isinstance(value, dict):
        return {key: mask_value(val) for key, val in value.items()}
    if isinstance(value, list):
        return [mask_value(val) for val in value]
    if isinstance(value, tuple):
        return tuple(mask_value(val) for val in value)
    return value


@dataclass(frozen=True)
class Span:
    """One node's contribution to a trace: name, timing, masked inputs."""

    name: str
    started_at: float
    ended_at: float
    inputs: dict[str, Any]
    error: str | None = None
    # True for a node that paused via LangGraph's interrupt() rather than
    # failed -- a deliberate, successful pause (see agents/clarify.py), not
    # something `error` should ever describe.
    paused: bool = False

    @property
    def duration_ms(self) -> float:
        return (self.ended_at - self.started_at) * 1000


@dataclass
class Trace:
    """Every span recorded for one turn on one thread."""

    thread_id: str
    spans: list[Span] = field(default_factory=list)


class Tracer:
    """Collects spans into one `Trace`. A fresh instance per turn keeps
    threads from leaking into each other's trace, matching how OmniState
    itself is fresh-per-invocation (see kernel/state.py)."""

    def __init__(self, thread_id: str):
        self.trace = Trace(thread_id=thread_id)

    @contextmanager
    def span(self, name: str, **inputs: Any) -> Iterator[None]:
        started = time.monotonic()
        error: str | None = None
        paused = False
        try:
            yield
        except GraphInterrupt:
            paused = True
            raise
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            ended = time.monotonic()
            self.trace.spans.append(
                Span(
                    name=name,
                    started_at=started,
                    ended_at=ended,
                    inputs=mask_value(inputs),
                    error=error,
                    paused=paused,
                )
            )
