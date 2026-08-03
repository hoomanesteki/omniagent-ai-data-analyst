"""Row cap gate: enforce maximum result set size limits."""

from typing import Any

from ..state import OmniState
from .exceptions import Unsafe


async def row_cap_gate(state: OmniState, *, config: dict[str, Any]) -> OmniState:
    """
    Row cap gate: if result row count would exceed max_rows, modify state.guarded to include the cap in assumptions.

    This gate enforces a limit on the number of rows returned by a query. If the result set
    would exceed the configured maximum, it records this constraint in the guarded ledger
    and adds an assumption to the state.

    Args:
        state: The OmniState to guard.
        config: Configuration dict that may contain 'max_rows' key.

    Returns:
        Modified state with cap constraints recorded in state.guarded and assumptions.

    Raises:
        Unsafe: If the result row count exceeds the configured max_rows limit.
    """
    # Extract max_rows from config, default to None (no limit)
    max_rows: int | None = config.get("max_rows")

    # Initialize guarded dict if needed
    if state.guarded is None:
        state.guarded = {}

    # If no max_rows configured, no cap is enforced
    if max_rows is None:
        state.guarded["row_cap_gate"] = {"status": "no_limit_configured"}
        return state

    # If no result_meta, we can't check row count; record as no data to check
    if state.result_meta is None:
        state.guarded["row_cap_gate"] = {"status": "no_result_meta", "max_rows": max_rows}
        return state

    # Extract row_count from result_meta (defensive check)
    row_count = state.result_meta.get("row_count")

    if row_count is None:
        state.guarded["row_cap_gate"] = {
            "status": "no_row_count_available",
            "max_rows": max_rows,
        }
        return state

    if not isinstance(row_count, (int, float)):
        try:
            row_count = (
                float(row_count)
                if isinstance(row_count, str) and "." in row_count
                else int(row_count)
            )
        except (TypeError, ValueError):
            state.guarded["row_cap_gate"] = {
                "status": "no_row_count_available",
                "max_rows": max_rows,
            }
            return state

    # Check if row count exceeds the cap
    if row_count > max_rows:
        reason = f"Result row count {row_count} exceeds max_rows limit {max_rows}"
        raise Unsafe(reason=reason)

    # Row count is within limits; record observation
    state.guarded["row_cap_gate"] = {
        "status": "within_limit",
        "max_rows": max_rows,
        "row_count": row_count,
        "cap_applied": True,
    }

    # Add assumption to state if not already present
    assumption_text = f"Result set limited to {max_rows} rows maximum"
    if assumption_text not in state.assumptions:
        state.assumptions.append(assumption_text)

    return state
