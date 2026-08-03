"""Individual guard gates for safety and policy enforcement."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..state import OmniState
from .empty_result import empty_result_gate
from .exceptions import Unsafe
from .llm_budget import llm_budget_gate
from .numeric_recompute import numeric_recompute_gate
from .pii_mask import pii_mask_gate
from .provenance import provenance_gate
from .row_cap import row_cap_gate
from .sql_allowlist import sql_allowlist_gate
from .timeout import timeout_gate


@dataclass
class GuardrailPolicy:
    """Policy defining a set of safety gates applied to state transitions."""

    gates: list[Callable[[OmniState], Any]] = field(default_factory=list)

    async def apply(self, state: OmniState) -> OmniState:
        """
        Run all gates in order without short-circuiting, so every gate
        leaves an audit trail regardless of earlier violations. Gates are
        async, so each is awaited — a bare call would just collect an
        unresolved coroutine instead of the gate's actual result.

        If any gate raises Unsafe, apply() still runs the remaining gates
        (for full audit coverage) but re-raises Unsafe once all gates have
        run, so the caller ultimately blocks the request. No-short-circuit
        governs audit visibility, not whether an unsafe outcome is
        tolerated.

        Args:
            state: The OmniState to guard.

        Returns:
            The modified state with guarded results populated.

        Raises:
            Unsafe: If any gate detected a violation, once all gates ran.
        """
        # Initialize guarded dict if needed
        if state.guarded is None:
            state.guarded = {}

        violations: list[Unsafe] = []

        # Run all gates and collect results
        for gate in self.gates:
            gate_name = gate.__name__
            try:
                state = await gate(state)
            except Unsafe as e:
                if state.guarded is None:
                    state.guarded = {}
                state.guarded[gate_name] = {"unsafe": True, "reason": e.reason}
                violations.append(e)
            except Exception as e:
                # Capture exception details but continue running other gates
                if state.guarded is None:
                    state.guarded = {}
                state.guarded[gate_name] = {
                    "error": str(e),
                    "exception_type": type(e).__name__,
                }

        if violations:
            raise Unsafe(reason="; ".join(v.reason for v in violations))

        return state


__all__ = [
    "Unsafe",
    "GuardrailPolicy",
    "empty_result_gate",
    "llm_budget_gate",
    "numeric_recompute_gate",
    "pii_mask_gate",
    "provenance_gate",
    "row_cap_gate",
    "sql_allowlist_gate",
    "timeout_gate",
]
