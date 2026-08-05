"""PII masking gate: mask declared-PII dimensions and PII-shaped values in
the actual result rows the caller is about to receive.

Runs as part of the same pre/post-execution `GuardrailPolicy.apply()` pass
every other gate runs in (`executor.py`, `fast_path.py`, `sql_agent.py`),
mutating `state.result_set` in place -- there is no separate result-store
indirection to keep in sync, and because this runs before `narrator_node`
ever reads `state.result_set`, a masked value can never leak back out
through the narration text either.

Two layers, since neither alone is enough:
  1. Column-name match against the semantic layer's declared PII
     dimensions (`Catalog.pii_dimensions()`) -- catches a declared-PII
     column under its governed-path or fast-path column alias
     (`customers__email`) even when its value doesn't look like anything
     in particular (a plain name, not an email or phone shape).
  2. Value-shape matching (`_mask_pii_value`) applied to every value in
     every row, independent of column name -- catches PII surfacing under
     an arbitrary alias, which is the normal case for `sql_agent`'s
     model-written SQL (a `SELECT email AS contact FROM ...` has no
     column name this gate can match against the catalog).
Layer 2 is a heuristic, not a guarantee: a value that has been reshaped
(concatenated, truncated, hashed) to no longer look like the pattern it
came from will not be caught. This is stated plainly rather than claimed
as complete.
"""

import re
from typing import Any

from ..state import OmniState

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_PHONE_RE = re.compile(r"(\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_PHONE_LOCAL_RE = re.compile(r"\b\d{3}[-.\s]\d{4}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD_RE = re.compile(r"\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b")


def _mask_pii_value(value: Any) -> Any:
    """Mask a single value if it matches a known PII shape (email, phone,
    SSN, card). Values that don't match any shape pass through unchanged --
    callers that already know a column is declared PII use `_redact` for a
    guaranteed mask instead of relying on this heuristic alone."""
    if value is None or not isinstance(value, str):
        return value

    value_str = value.strip()
    if not value_str:
        return value

    if _EMAIL_RE.fullmatch(value_str):
        return "***@***.***"
    if _PHONE_RE.fullmatch(value_str) or _PHONE_LOCAL_RE.fullmatch(value_str):
        return "***-***-****"
    if _SSN_RE.fullmatch(value_str):
        return "***-**-****"
    if _CARD_RE.fullmatch(value_str):
        return "****-****-****-****"
    return value


def _redact(value: Any) -> Any:
    """Unconditional mask for a column the catalog has declared PII,
    regardless of whether the value happens to match a known shape."""
    if value is None:
        return None
    masked = _mask_pii_value(value)
    return masked if masked != value else "***"


def _pii_column_keys(catalog: Any) -> set[str]:
    """Every result-row column key a declared-PII dimension could appear
    under: the bare dimension name (`email`), the qualified name with `.`
    (`customers.email`), and the compiled alias with `__`
    (`customers__email` -- see `narrator.py`'s identical `.replace('.', '__')`
    convention for how the semantic compiler names breakdown columns)."""
    keys: set[str] = set()
    for qualified in catalog.pii_dimensions():
        keys.add(qualified)
        keys.add(qualified.replace(".", "__"))
        if "." in qualified:
            keys.add(qualified.split(".", 1)[1])
    return keys


async def pii_mask_gate(state: OmniState, *, config: dict[str, Any]) -> OmniState:  # noqa: C901
    """Mask PII in `state.result_set` in place. Never raises -- a masking
    failure degrades to the value-shape heuristic rather than blocking the
    turn, and is recorded in `state.guarded` either way."""
    if state.guarded is None:
        state.guarded = {}

    if not state.result_set:
        state.guarded["pii_mask_gate"] = {"status": "no_result_set", "masked": False}
        return state

    semantic_provider = config.get("semantic_provider")
    pii_keys: set[str] = set()
    if semantic_provider is not None and state.dataset_id:
        try:
            catalog = semantic_provider.catalog(state.dataset_id)
            pii_keys = _pii_column_keys(catalog)
        except Exception as e:
            state.guarded["pii_mask_gate"] = {
                "status": "catalog_lookup_failed",
                "error": str(e),
                "masked": False,
            }
            # Still fall through to the value-shape heuristic below --
            # not knowing the declared-PII columns is not a reason to skip
            # the pattern-based layer that doesn't need them.

    masked_columns: set[str] = set()
    for row in state.result_set:
        if not isinstance(row, dict):
            continue
        for key, value in list(row.items()):
            if key in pii_keys:
                new_value = _redact(value)
                if new_value != value:
                    masked_columns.add(key)
                row[key] = new_value
            else:
                new_value = _mask_pii_value(value)
                if new_value != value:
                    masked_columns.add(key)
                    row[key] = new_value

    if masked_columns:
        state.guarded["pii_mask_gate"] = {
            "status": "masked",
            "masked": True,
            "pii_columns_masked": sorted(masked_columns),
        }
        assumption = "Result includes masked PII columns (emails, phone numbers, etc.)"
        if assumption not in state.assumptions:
            state.assumptions.append(assumption)
    elif "pii_mask_gate" not in state.guarded:
        state.guarded["pii_mask_gate"] = {"status": "no_pii_found", "masked": False}

    return state
