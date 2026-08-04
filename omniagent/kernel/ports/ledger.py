"""Answer ledger: a durable audit record of every governed turn."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class LedgerEntry:
    """One turn's audit record.

    `question` is expected to already be masked by the caller (see
    kernel/telemetry.py's `mask_value`) before it ever reaches a ledger
    implementation -- the ledger itself does not re-mask, matching how
    the gate stack expects its own inputs already validated rather than
    re-checking them defensively.
    """

    trace_id: str
    thread_id: str
    dataset_id: str
    question: str
    route: str | None
    matched_metric: str | None
    executed_sql: str | None
    confidence: float | None
    error: str | None
    created_at: datetime


class AnswerLedgerStore(Protocol):
    """Durable audit trail for governed answers."""

    def record(self, entry: LedgerEntry) -> None:
        """Persist one turn's audit record."""
        ...

    def for_thread(self, thread_id: str) -> list[LedgerEntry]:
        """Every recorded entry for one thread, oldest first."""
        ...
