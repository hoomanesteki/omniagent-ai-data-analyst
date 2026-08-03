"""PII masking gate: inspect semantic layer and mask PII columns in results."""

import re
from typing import Any

from ..state import OmniState


def _get_pii_columns(semantic_provider: Any, dataset_id: str) -> dict[str, bool]:  # noqa: C901
    """
    Extract PII column metadata from semantic provider catalog.

    Args:
        semantic_provider: The semantic provider (catalog source).
        dataset_id: The dataset identifier.

    Returns:
        Dictionary mapping column names to pii=True flag.
    """
    try:
        if not semantic_provider:
            return {}

        catalog = semantic_provider.catalog(dataset_id)
        if not catalog or not isinstance(catalog, dict):
            return {}

        pii_columns = {}
        # Traverse catalog looking for columns with pii=True
        # Catalog structure may be: {tables: {table_name: {columns: {col_name: {pii: True}}}}}
        if "tables" in catalog:
            for table_meta in catalog.get("tables", {}).values():
                if isinstance(table_meta, dict):
                    for col_name, col_meta in table_meta.get("columns", {}).items():
                        if isinstance(col_meta, dict) and col_meta.get("pii") is True:
                            pii_columns[col_name] = True

        # Alternative structure: flat column definitions
        if "columns" in catalog:
            for col_name, col_meta in catalog.get("columns", {}).items():
                if isinstance(col_meta, dict) and col_meta.get("pii") is True:
                    pii_columns[col_name] = True

        return pii_columns
    except Exception:
        # Defensive: if catalog access fails, continue without PII metadata
        return {}


def _mask_pii_value(value: Any) -> str | None:
    """
    Apply PII masking to a single value using heuristic patterns.

    Masks common PII types: emails, phone numbers, SSNs, credit cards, etc.

    Args:
        value: The value to potentially mask.

    Returns:
        Masked string representation, or original string if not PII-like.
    """
    if value is None:
        return None

    value_str = str(value).strip()
    if not value_str:
        return value_str

    # Email pattern: anything@anything.anything. Local part includes "+"
    # since tagged addresses (user+tag@domain.com) are valid, common email
    # syntax — excluding them would under-mask real PII.
    if re.match(r"[\w\.+-]+@[\w\.-]+\.\w+", value_str):
        return "***@***.***"

    # Phone number patterns: (123) 456-7890, 123-456-7890, 1234567890, 555-1234
    # Anchored at the end so a longer plain-digit run (e.g. a 16-digit card
    # number) isn't misdetected via a matching 10-digit prefix.
    if re.match(r"(\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}$", value_str):
        return "***-***-****"

    # Local 7-digit format (3-4 grouping): 555-1234
    if re.match(r"\d{3}[-.\s]\d{4}$", value_str):
        return "***-***-****"

    # SSN pattern: 123-45-6789
    if re.match(r"\d{3}-\d{2}-\d{4}", value_str):
        return "***-**-****"

    # Credit card pattern: 16 digits grouped with spaces/dashes. The separator
    # is required (not optional) so a bare 16-digit run isn't misdetected as
    # a card number — plain digit sequences pass through unmasked.
    if re.match(r"\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}$", value_str):
        return "****-****-****-****"

    # Passport/ID pattern: alphanumeric sequences 6+ chars that look like IDs
    # This is conservative to avoid masking legitimate non-PII strings

    return value_str


def _mask_result_table(result_table: Any, pii_columns: dict[str, bool]) -> Any:  # noqa: C901
    """
    Create a masked copy of a result table.

    Masks values in columns marked as PII. Handles Arrow tables and pandas DataFrames.

    Args:
        result_table: The result table (Arrow or DataFrame).
        pii_columns: Dictionary of column names marked as pii=True.

    Returns:
        Masked copy of the result table, or original if no masking needed.
    """
    if not pii_columns:
        return result_table

    try:
        # If result_table is a list of dicts — checked before the generic
        # `.copy()` branch below, since list also defines `.copy()` and would
        # otherwise be misrouted into the DataFrame path and fail silently.
        if isinstance(result_table, list):
            masked = []
            for row in result_table:
                if isinstance(row, dict):
                    masked_row = row.copy()
                    for col in pii_columns:
                        if col in masked_row:
                            masked_row[col] = _mask_pii_value(masked_row[col])
                    masked.append(masked_row)
                else:
                    masked.append(row)
            return masked

        # Try to handle as Arrow table (RecordBatchReader or Table)
        if hasattr(result_table, "to_pandas"):
            # Arrow table: convert to pandas, mask, convert back
            df = result_table.to_pandas()
            for col in pii_columns:
                if col in df.columns:
                    df[col] = df[col].apply(_mask_pii_value)
            # Convert back to Arrow
            import pyarrow as pa

            return pa.Table.from_pandas(df)

        # Try to handle as pandas DataFrame
        if hasattr(result_table, "copy") and hasattr(result_table, "columns"):
            df = result_table.copy()
            for col in pii_columns:
                if col in df.columns:
                    df[col] = df[col].apply(_mask_pii_value)
            return df

        # If we can't handle it, return original
        return result_table
    except Exception:
        # Defensive: if masking fails, return original (don't break the pipeline)
        return result_table


async def pii_mask_gate(state: OmniState, *, config: dict[str, Any]) -> OmniState:  # noqa: C901
    """PII masking gate: inspect semantic layer for columns marked pii=True.

    If result includes PII columns, mask them (e.g., emails → "***@***.***").
    Update state.result_ref to point to masked version. Do NOT raise; return
    modified state.

    This gate:
    1. Retrieves the semantic catalog to find PII-marked columns
    2. Loads the result table from state.result_ref
    3. Applies masking to PII columns (deterministic patterns)
    4. Stores the masked result and updates state.result_ref

    Defensive behavior: if result_ref is None, dataset_id is empty, or semantic
    provider/result_store are unavailable, returns unmodified state (no error raised).
    All observations are recorded in state.guarded for audit trail.

    Args:
        state: The OmniState to guard.
        config: Configuration dict that may contain:
            - semantic_provider: SemanticProvider instance
            - result_store: ResultStore instance
            - principal: Principal for result store access

    Returns:
        Modified state with masked result_ref (if masking applied), or unmodified
        state if no PII columns found or dependencies unavailable.
    """
    # Initialize guarded dict if needed
    if state.guarded is None:
        state.guarded = {}

    # Defensive: if no result_ref, nothing to mask
    if not state.result_ref:
        state.guarded["pii_mask_gate"] = {
            "status": "no_result_ref",
            "masked": False,
        }
        return state

    # Defensive: if no dataset_id, can't access semantic catalog
    if not state.dataset_id:
        state.guarded["pii_mask_gate"] = {
            "status": "no_dataset_id",
            "masked": False,
        }
        return state

    # Extract dependencies from config
    semantic_provider = config.get("semantic_provider")
    result_store = config.get("result_store")
    principal = config.get("principal")

    # Defensive: if no semantic provider or result store, skip masking
    if not semantic_provider or not result_store:
        state.guarded["pii_mask_gate"] = {
            "status": "dependencies_unavailable",
            "masked": False,
        }
        return state

    # Step 1: Get PII column definitions from semantic layer
    pii_columns = _get_pii_columns(semantic_provider, state.dataset_id)

    if not pii_columns:
        # No PII columns marked in catalog
        state.guarded["pii_mask_gate"] = {
            "status": "no_pii_columns_found",
            "masked": False,
            "pii_column_count": 0,
        }
        return state

    # Step 2: Retrieve result table from result store
    try:
        result_table = result_store.get(state.result_ref, principal=principal)
    except Exception as e:
        # Defensive: if retrieval fails, record and return unmodified
        state.guarded["pii_mask_gate"] = {
            "status": "result_retrieval_failed",
            "error": str(e),
            "masked": False,
        }
        return state

    # Defensive: if result table is None or empty, no masking needed
    if result_table is None:
        state.guarded["pii_mask_gate"] = {
            "status": "empty_result",
            "masked": False,
        }
        return state

    # Step 3: Apply masking to PII columns
    try:
        masked_table = _mask_result_table(result_table, pii_columns)
    except Exception as e:
        # Defensive: if masking fails, record and return unmodified
        state.guarded["pii_mask_gate"] = {
            "status": "masking_failed",
            "error": str(e),
            "masked": False,
        }
        return state

    # Step 4: Store masked result and update result_ref
    try:
        masked_ref = result_store.put(
            masked_table,
            principal=principal,
            ttl_s=900,  # Same TTL as typical result store
        )

        # Update state to point to masked result
        state.result_ref = masked_ref

        # Record successful masking
        state.guarded["pii_mask_gate"] = {
            "status": "masked_successfully",
            "masked": True,
            "pii_columns_masked": list(pii_columns.keys()),
            "original_ref": state.result_ref,  # Note: this is now the new ref
            "masking_type": "deterministic_patterns",
        }

        # Add assumption about masking
        assumption = "Result includes masked PII columns (emails, phone numbers, etc.)"
        if assumption not in state.assumptions:
            state.assumptions.append(assumption)

    except Exception as e:
        # Defensive: if storing masked result fails, record but return original
        state.guarded["pii_mask_gate"] = {
            "status": "storage_failed",
            "error": str(e),
            "masked": False,
        }
        return state

    return state
