"""Timeout gate: track query execution time and enforce timeout limits."""

import time
from typing import Any

from ..state import OmniState


async def timeout_gate(state: OmniState, *, config: dict[str, Any]) -> OmniState:
    """Timeout gate: track query execution time.

    If execution time exceeds timeout_ms, raise Unsafe(reason="query timeout").
    Uses time.time() to measure (deterministic in tests with frozen time).

    Args:
        state: The OmniState to guard.
        config: Configuration dict with optional 'timeout_ms' key (int, milliseconds).

    Returns:
        The modified state with timing observation recorded.

    Raises:
        Unsafe: If query execution time exceeds configured timeout_ms.
    """
    timeout_ms = config.get("timeout_ms")

    # If no timeout configured, pass through
    if timeout_ms is None:
        return state

    # Initialize guarded dict if needed
    if state.guarded is None:
        state.guarded = {}

    gate_data = state.guarded.get("timeout_gate", {})

    if "start_time" not in gate_data:
        # First call - initialize timing
        gate_data["start_time"] = time.time()
        gate_data["timeout_ms"] = timeout_ms
        state.guarded["timeout_gate"] = gate_data
        return state

    # Check elapsed time on subsequent calls
    start_time = gate_data["start_time"]
    current_time = time.time()
    elapsed_ms = (current_time - start_time) * 1000

    if elapsed_ms > timeout_ms:
        from . import Unsafe

        raise Unsafe(reason="query timeout")

    return state
