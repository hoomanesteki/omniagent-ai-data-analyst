"""Empty result gate: enforce abstention when query returns no rows."""

import re
from typing import Any

from ..state import OmniState


async def empty_result_gate(state: OmniState, *, config: dict[str, Any]) -> OmniState:
    """Empty result gate: if query returns 0 rows, set state.guarded.abstain=True.

    Ensure state.guarded.narration contains no numeric values (or None).
    Do NOT raise exception; return modified state.

    This gate enforces abstention when a database query returns zero rows,
    preventing spurious answers. It also validates that any guarded narration
    does not embed numeric values, which could mask the empty result.

    Args:
        state: The OmniState to guard.
        config: Optional configuration dict (unused in this implementation).

    Returns:
        The modified state with guarded observation recorded.

    Raises:
        Unsafe: If narration contains numeric values that could mislead.
    """
    # Defensive: initialize guarded dict if needed
    if state.guarded is None:
        state.guarded = {}

    # Check if result_meta indicates zero rows
    is_empty_result = False
    row_count: int | None = None

    if state.result_meta is not None and isinstance(state.result_meta, dict):
        row_count = state.result_meta.get("row_count")
        if row_count is not None and isinstance(row_count, int):
            is_empty_result = row_count == 0

    # Record observation in guarded ledger
    state.guarded["empty_result_gate"] = {
        "is_empty": is_empty_result,
        "row_count": row_count,
        "has_result_meta": state.result_meta is not None,
    }

    # Set abstain flag if result is empty
    if is_empty_result:
        state.guarded["abstain"] = True

    # Validate narration: ensure no numeric values present
    # Check both state.guarded["narration"] and state.narration
    narration: str | None = None
    if "narration" in state.guarded and isinstance(state.guarded.get("narration"), str):
        narration = state.guarded["narration"]
    elif state.narration is not None and isinstance(state.narration, str):
        narration = state.narration

    if narration is not None:
        # Pattern to detect numeric values: integers, floats, scientific notation, etc.
        # This includes patterns like "123", "45.67", "1e-5", etc.
        numeric_pattern = r"\b\d+\.?\d*([eE][+-]?\d+)?\b|\b\d*\.\d+([eE][+-]?\d+)?\b"
        if re.search(numeric_pattern, narration):
            # Import Unsafe here to avoid circular imports
            from . import Unsafe

            # Raise Unsafe if narration contains numeric values
            reason = (
                f"Narration contains numeric values which may mask empty result: {narration[:100]}"
            )
            raise Unsafe(reason=reason)

    return state
