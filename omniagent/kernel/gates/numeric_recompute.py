"""Numeric recompute gate: validate numeric claims against computed values."""

import re
from statistics import mean
from typing import Any

from ..state import OmniState
from .exceptions import Unsafe


async def numeric_recompute_gate(state: OmniState, *, config: dict[str, Any]) -> OmniState:
    """
    Numeric recompute gate: extract all numeric claims from state.narration.

    Recompute them from state.result_set (sum, count, avg as appropriate).
    If mismatch > 5%, raise Unsafe(reason="number mismatch: ...").
    Otherwise return state unchanged.

    Args:
        state: The OmniState to validate.
        config: Configuration dict (optional threshold override via config.get("threshold")).

    Returns:
        The unchanged state if all numeric claims validate.

    Raises:
        Unsafe: If numeric claims in narration don't match recomputed values by > threshold%.
    """
    # Defensive: if no narration or no result_set, nothing to validate
    if not state.narration or not state.result_set:
        return state

    # Get threshold from config or use default 5%
    threshold_pct = config.get("threshold", 5.0)

    # Extract all numbers from narration
    extracted_numbers = _extract_numbers_from_narration(state.narration)

    if not extracted_numbers:
        # No numeric claims to validate
        return state

    # Recompute values from result_set
    recomputed = _recompute_from_result_set(state.result_set)

    if not recomputed:
        # Could not compute any values, but extracted claims exist
        # This is suspicious but not necessarily unsafe if result_set is incomplete
        return state

    # Validate each extracted number against recomputed values
    mismatches = []
    for claim in extracted_numbers:
        claim_value = claim["value"]
        claim_context = claim["context"]

        # Find matching recomputed value
        matching_computed = _find_matching_computed_value(claim_value, claim_context, recomputed)

        if matching_computed is not None:
            mismatch_pct = _calculate_mismatch_percentage(claim_value, matching_computed)

            if mismatch_pct > threshold_pct:
                mismatches.append(
                    {
                        "claimed": claim_value,
                        "computed": matching_computed,
                        "context": claim_context,
                        "mismatch_pct": mismatch_pct,
                    }
                )

    if mismatches:
        reason = _format_mismatch_reason(mismatches)
        raise Unsafe(reason=reason)

    return state


def _extract_numbers_from_narration(narration: str) -> list[dict[str, Any]]:
    """
    Extract all numeric values from narration text.

    Args:
        narration: Text to extract numbers from.

    Returns:
        List of dicts with keys: value (float), context (str describing the context).
    """
    extracted: list[dict[str, Any]] = []

    # Pattern to match numbers (integers and floats with optional commas/thousands separators)
    # Also captures surrounding words for context
    pattern = r"(?:^|[\s,])([\d,]+(?:\.\d+)?)\s*([a-z]*)"

    for match in re.finditer(pattern, narration, re.IGNORECASE):
        try:
            # Parse the number, removing any thousands separators
            number_str = match.group(1).replace(",", "")
            value = float(number_str)

            # Get surrounding context to understand if it's a count, sum, or average
            start_pos = max(0, match.start() - 20)
            end_pos = min(len(narration), match.end() + 20)
            context_text = narration[start_pos:end_pos].lower()

            # Identify context
            context = _identify_numeric_context(value, context_text)

            extracted.append(
                {
                    "value": value,
                    "context": context,
                    "position": match.start(),
                }
            )
        except ValueError:
            # Skip unparseable numbers
            continue

    # Sort by position and deduplicate very similar values at nearby positions
    extracted = _deduplicate_nearby_numbers(extracted)

    return extracted


def _identify_numeric_context(value: float, context_text: str) -> str:
    """
    Identify whether a number represents a count, sum, or average.

    Args:
        value: The numeric value.
        context_text: Surrounding text for context.

    Returns:
        String: "count", "sum", "average", or "unknown".
    """
    context_lower = context_text.lower()

    # Check for explicit keywords
    if any(word in context_lower for word in ["count", "total items", "records", "rows"]):
        return "count"

    if any(word in context_lower for word in ["sum", "total"]):
        return "sum"

    if any(word in context_lower for word in ["average", "avg", "mean"]):
        return "average"

    # Heuristic: small integers are often counts, larger numbers could be sums
    if value == int(value) and value < 1000:
        return "count"

    return "unknown"


def _recompute_from_result_set(result_set: Any) -> dict[str, Any]:  # noqa: C901
    """
    Recompute numeric aggregations from result_set.

    Args:
        result_set: Result data (list of dicts, list of lists, or similar).

    Returns:
        Dict with keys: count, sum_all, average_all, and per-column stats.
    """
    recomputed: dict[str, Any] = {
        "count": 0,
        "sum_all": 0.0,
        "average_all": 0.0,
        "columns": {},
    }

    # Handle None or empty result_set
    if not result_set:
        return recomputed

    # Extract rows of data
    rows = []
    if isinstance(result_set, list):
        rows = result_set
    elif hasattr(result_set, "__iter__"):
        try:
            rows = list(result_set)
        except (TypeError, ValueError):
            return recomputed
    else:
        return recomputed

    if not rows:
        return recomputed

    # Count rows
    recomputed["count"] = len(rows)

    # Extract numeric values and compute aggregations
    all_numeric_values = []

    for row in rows:
        if isinstance(row, dict):
            for key, val in row.items():
                if isinstance(val, (int, float)):
                    all_numeric_values.append(val)
                    if key not in recomputed["columns"]:
                        recomputed["columns"][key] = {"values": [], "sum": 0, "count": 0}
                    recomputed["columns"][key]["values"].append(val)
                    recomputed["columns"][key]["count"] += 1
                    recomputed["columns"][key]["sum"] += val
        elif isinstance(row, (list, tuple)):
            for i, val in enumerate(row):
                if isinstance(val, (int, float)):
                    all_numeric_values.append(val)
                    col_key = f"col_{i}"
                    if col_key not in recomputed["columns"]:
                        recomputed["columns"][col_key] = {"values": [], "sum": 0, "count": 0}
                    recomputed["columns"][col_key]["values"].append(val)
                    recomputed["columns"][col_key]["count"] += 1
                    recomputed["columns"][col_key]["sum"] += val
        elif isinstance(row, (int, float)):
            all_numeric_values.append(row)

    # Compute overall statistics
    if all_numeric_values:
        recomputed["sum_all"] = sum(all_numeric_values)
        recomputed["average_all"] = mean(all_numeric_values)

    # Compute per-column statistics
    for col_data in recomputed["columns"].values():
        if col_data["values"]:
            col_data["average"] = col_data["sum"] / col_data["count"]

    return recomputed


def _find_matching_computed_value(
    claimed_value: float, context: str, recomputed: dict[str, Any]
) -> float | None:
    """
    Find the best candidate computed value to compare against a claim.

    Prefers the candidate matching the claim's inferred context, but always
    also considers every other recomputed value as a fallback: the
    narration-context heuristic is approximate (e.g. a small integer
    defaults to "count" even when it's really a sum), and a claim with no
    close match anywhere in the data is exactly what this gate exists to
    catch — it must not be silently skipped just because it missed its
    guessed category. Returns None only when the result set produced no
    computed values at all (nothing to validate against).

    Args:
        claimed_value: The claimed value.
        context: Context string ("count", "sum", "average", "unknown").
        recomputed: Recomputed stats dict.

    Returns:
        The closest matching computed value, or None if there is no data.
    """
    has_data = (
        recomputed["count"] != 0
        or recomputed["sum_all"] != 0
        or recomputed["average_all"] != 0
        or bool(recomputed["columns"])
    )
    if not has_data:
        return None

    candidates: list[float] = []

    if context == "count":
        candidates.append(float(recomputed["count"]))
    elif context == "sum":
        candidates.append(recomputed["sum_all"])
    elif context == "average":
        candidates.append(recomputed["average_all"])

    # Fallback: every other recomputed value, regardless of context.
    candidates.append(float(recomputed["count"]))
    candidates.append(recomputed["sum_all"])
    candidates.append(recomputed["average_all"])
    for col_data in recomputed["columns"].values():
        candidates.append(col_data["sum"])
        if "average" in col_data:
            candidates.append(col_data["average"])

    return min(candidates, key=lambda c: abs(c - claimed_value))


def _calculate_mismatch_percentage(claimed: float, computed: float) -> float:
    """
    Calculate percentage mismatch between claimed and computed values.

    Args:
        claimed: Claimed value.
        computed: Computed value.

    Returns:
        Mismatch percentage.
    """
    if claimed == 0 and computed == 0:
        return 0.0

    if computed == 0:
        # Avoid division by zero; if computed is 0 but claimed is not, that's 100% mismatch
        return 100.0 if claimed != 0 else 0.0

    return abs(claimed - computed) / abs(computed) * 100.0


def _deduplicate_nearby_numbers(numbers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Remove duplicate or very similar numbers at nearby positions.

    Args:
        numbers: List of extracted numbers.

    Returns:
        Deduplicated list.
    """
    if not numbers:
        return []

    # Sort by position
    sorted_nums = sorted(numbers, key=lambda x: x["position"])

    # Keep track of indices to remove
    to_remove = set()

    for i in range(len(sorted_nums) - 1):
        curr = sorted_nums[i]
        next_item = sorted_nums[i + 1]

        # If values are very close and positions are nearby, consider it a duplicate
        if (
            abs(curr["position"] - next_item["position"]) < 30
            and abs(curr["value"] - next_item["value"]) < 0.01
        ):
            # Keep the first occurrence, mark the second for removal
            to_remove.add(i + 1)

    return [num for i, num in enumerate(sorted_nums) if i not in to_remove]


def _format_mismatch_reason(mismatches: list[dict[str, Any]]) -> str:
    """
    Format a human-readable reason string for mismatches.

    Args:
        mismatches: List of mismatch dicts.

    Returns:
        Formatted reason string.
    """
    if not mismatches:
        return "number mismatch detected"

    details = []
    for mm in mismatches[:3]:  # Limit to first 3 for readability
        details.append(
            f"claimed {mm['context']}={mm['claimed']}, "
            f"computed={mm['computed']:.2f} ({mm['mismatch_pct']:.1f}% mismatch)"
        )

    reason = "number mismatch: " + "; ".join(details)
    if len(mismatches) > 3:
        reason += f" (and {len(mismatches) - 3} more mismatches)"

    return reason
