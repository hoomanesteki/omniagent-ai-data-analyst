"""Provenance gate: add metadata to numeric values tracking their origin and lineage."""

import re
from decimal import Decimal
from typing import Any

from ..state import OmniState
from .exceptions import Unsafe


def _extract_table_info_from_sql(sql: str | None) -> dict[str, list[str]]:  # noqa: C901
    """
    Deterministically extract table names and column references from SQL.
    Returns dict mapping table names to columns mentioned from that table.

    Raises Unsafe if SQL contains forbidden operations.
    """
    if not sql:
        return {}

    tables_and_cols: dict[str, list[str]] = {}

    # Detect forbidden operations (security gate)
    forbidden_patterns = [
        r"\bDROP\b",
        r"\bDELETE\b",
        r"\bINSERT\b",
        r"\bUPDATE\b",
        r"\bALTER\b",
        r"\bCREATE\b",
        r"\bTRUNCATE\b",
        r"\bMERGE\b",
    ]

    for pattern in forbidden_patterns:
        if re.search(pattern, sql, re.IGNORECASE):
            raise Unsafe(reason=f"SQL contains forbidden operation: {pattern}")

    # Extract table names from FROM and JOIN clauses
    # Pattern: FROM|JOIN table_name (with optional aliases). The trailing
    # alias group excludes SQL keywords via negative lookahead — otherwise a
    # bare alias-less join ("FROM t1 JOIN t2 ...") lets the alias slot
    # swallow the next clause's own JOIN/ON keyword, hiding it from the next
    # finditer scan and dropping that table entirely.
    table_pattern = (
        r'(?:FROM|JOIN)\s+(?:"?(\w+)"?|\(SELECT[^)]*\))\s*(?:AS\s+)?'
        r"(?!(?:JOIN|ON|WHERE|GROUP|ORDER|LIMIT)\b)(\w+)?"
    )
    for match in re.finditer(table_pattern, sql, re.IGNORECASE):
        table_name = match.group(1) or match.group(2)
        if table_name and table_name.upper() not in ("SELECT",):
            tables_and_cols.setdefault(table_name, [])

    # Extract column references (simplified: table.column or alias.column)
    col_pattern = r'(?:^|\s|,)(?:"?(\w+)"?\."?(\w+)"?|\b(\w+)\b)(?:\s|,|$)'
    for match in re.finditer(col_pattern, sql):
        # Avoid common SQL keywords
        keywords = {"SELECT", "FROM", "WHERE", "GROUP", "ORDER", "LIMIT", "JOIN", "ON", "AS"}
        if match.group(1):  # table.column form
            table = match.group(1)
            col = match.group(2)
            if table not in keywords and col not in keywords:
                if table in tables_and_cols:
                    tables_and_cols[table].append(col)
        elif match.group(3):  # bare column
            col = match.group(3)
            if col not in keywords:
                # For bare columns, assign to first available table
                for table in tables_and_cols:
                    if col not in tables_and_cols[table]:
                        tables_and_cols[table].append(col)
                    break

    return tables_and_cols


def _is_numeric(value: Any) -> bool:
    """Check if a value is numeric (int, float, Decimal, or string representation)."""
    if isinstance(value, (int, float, Decimal)):
        return True
    if isinstance(value, str):
        try:
            float(value)
            return True
        except (ValueError, TypeError):
            return False
    return False


def _extract_filters_from_sql(sql: str | None) -> list[str]:
    """Extract filter predicates from WHERE clause."""
    if not sql:
        return []

    filters = []
    # Simple pattern: extract WHERE ... (until GROUP, ORDER, LIMIT, or end)
    where_match = re.search(
        r"WHERE\s+(.+?)(?:GROUP\s+BY|ORDER\s+BY|LIMIT|$)", sql, re.IGNORECASE | re.DOTALL
    )
    if where_match:
        where_clause = where_match.group(1).strip()
        # Split by AND/OR and clean up
        predicates = re.split(r"\s+(?:AND|OR)\s+", where_clause, flags=re.IGNORECASE)
        filters = [p.strip() for p in predicates if p.strip()]

    return filters


def _add_provenance_annotation(spec: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    """Add provenance metadata to chart/table specification."""
    if not spec:
        return spec

    # Create a shallow copy to avoid mutation
    annotated = dict(spec)

    # Add provenance to chart annotations or metadata
    if "annotation" not in annotated:
        annotated["annotation"] = {}

    annotated["annotation"]["provenance"] = {
        "tables": provenance.get("tables", []),
        "filters": provenance.get("filters", []),
        "sql": provenance.get("executed_sql", ""),
    }

    return annotated


async def provenance_gate(state: OmniState, *, config: dict[str, Any]) -> OmniState:
    """
    Provenance gate: add metadata to every numeric value with:
    {value, table, column, filters_applied}.

    Chart and table both include provenance in annotations.
    No exception on missing data; return modified state defensively.
    Raise Unsafe(reason=...) only on actual violations (forbidden SQL ops).

    Args:
        state: The OmniState to process.
        config: Gate configuration dict (may contain tolerance thresholds, etc.)

    Returns:
        Modified state with provenance metadata added to guarded dict and result structures.

    Raises:
        Unsafe: If executed SQL contains forbidden operations (DROP, INSERT, etc.)
    """

    # Initialize guarded dict if needed
    if state.guarded is None:
        state.guarded = {}

    provenance_result: dict[str, Any] = {
        "status": "ok",
        "numeric_values_tracked": 0,
        "tables_identified": [],
        "filters_applied": [],
    }

    # Defensively handle missing or None fields
    executed_sql = state.executed_sql
    result_meta = state.result_meta or {}
    chart_spec = state.chart_spec or {}

    # Parse SQL to extract table and column information
    # This will raise Unsafe if forbidden operations are detected
    table_info = {}
    filters = []

    if executed_sql:
        table_info = _extract_table_info_from_sql(executed_sql)
        filters = _extract_filters_from_sql(executed_sql)
        provenance_result["tables_identified"] = list(table_info.keys())
        provenance_result["filters_applied"] = filters

    # Collect numeric values and their provenance from result_meta
    numeric_values_with_provenance: list[dict[str, Any]] = []

    if result_meta and isinstance(result_meta, dict):
        # Process metrics/values from result_meta
        for key, value in result_meta.items():
            if _is_numeric(value):
                numeric_values_with_provenance.append(
                    {
                        "name": key,
                        "value": value,
                        "tables": list(table_info.keys()),
                        "filters": filters,
                        "executed_sql": executed_sql or "",
                    }
                )
                provenance_result["numeric_values_tracked"] += 1

    # Add provenance annotations to chart if present
    if chart_spec:
        annotated_chart = _add_provenance_annotation(
            chart_spec,
            {
                "tables": list(table_info.keys()),
                "filters": filters,
                "executed_sql": executed_sql or "",
            },
        )
        state.chart_spec = annotated_chart

    # Store provenance ledger in guarded dict
    provenance_result["values"] = numeric_values_with_provenance
    state.guarded["provenance_gate"] = provenance_result

    return state
