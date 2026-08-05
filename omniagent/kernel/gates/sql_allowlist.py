"""SQL guard gate: reject DROP, CREATE, DML-in-CTE, stacked statements."""

import re
from typing import Any

from ..state import OmniState
from .exceptions import Unsafe


async def sql_allowlist_gate(state: OmniState, *, config: dict[str, Any]) -> OmniState:  # noqa: C901
    """
    SQL guard: reject DROP, CREATE, DML-in-CTE, stacked statements.

    Check query against a configurable block list. Raises Unsafe(reason=...) on match.
    Test cases from 09_MLOPS_CICD_CT.md §19.1.5.

    Args:
        state: Current OmniState containing executed_sql to validate.
        config: Configuration dict with optional keys:
            - "blocked_keywords": list[str] - SQL keywords to reject (default: DROP, CREATE, ALTER, DELETE, INSERT, UPDATE, TRUNCATE)
            - "max_statements": int - Maximum number of SQL statements allowed (default: 1)
            - "reject_cte_with_dml": bool - Reject DML operations in CTEs (default: True)
            - "custom_blocklist": list[str] - Custom regex patterns to reject (default: [])

    Returns:
        The modified state with guarded results populated (or unmodified on pass).

    Raises:
        Unsafe: If SQL violates safety policy with a specific reason.
    """
    # Be defensive: handle missing or empty SQL
    sql = state.executed_sql
    if not sql or not isinstance(sql, str):
        return state

    # Extract config with sensible defaults
    blocked_keywords = config.get(
        "blocked_keywords",
        [
            "DROP",
            "CREATE",
            "ALTER",
            "DELETE",
            "INSERT",
            "UPDATE",
            "TRUNCATE",
            # These do not write to the database file, so `read_only=True`
            # alone does not stop them (see docs/adr/0005): COPY/EXPORT write
            # to the filesystem, ATTACH/INSTALL/LOAD pull in another database
            # or extension, PRAGMA/SET/CALL/VACUUM/CHECKPOINT/ANALYZE change
            # session or database state, GRANT/REVOKE/COMMENT touch schema
            # metadata.
            "COPY",
            "EXPORT",
            "ATTACH",
            "DETACH",
            "PRAGMA",
            "INSTALL",
            "LOAD",
            "CALL",
            "SET",
            "VACUUM",
            "CHECKPOINT",
            "ANALYZE",
            "GRANT",
            "REVOKE",
            "COMMENT",
        ],
    )
    max_statements = config.get("max_statements", 1)
    reject_cte_with_dml = config.get("reject_cte_with_dml", True)
    custom_blocklist = config.get("custom_blocklist", [])

    # Normalize SQL: remove comments and extra whitespace
    normalized_sql = _normalize_sql(sql)

    # Check 0: table functions that read from the filesystem or network can
    # appear inside an otherwise-valid SELECT (e.g. `read_csv_auto('/etc/passwd')`
    # or `read_parquet('s3://...')`), so the SELECT-only check further down does
    # not by itself stop them.
    if _contains_file_or_network_read(normalized_sql):
        raise Unsafe(
            reason="Reading external files or network locations (read_csv, "
            "read_parquet, read_json, glob, http(s)://, s3://) is not allowed."
        )

    # Check 1: Reject stacked statements (multiple SQL statements)
    statement_count = _count_sql_statements(normalized_sql)
    if statement_count > max_statements:
        raise Unsafe(
            reason=f"Multiple SQL statements detected ({statement_count} > {max_statements}). "
            "Only single queries are allowed."
        )

    # Check 2: Reject blocked keywords (DROP, CREATE, etc.)
    for keyword in blocked_keywords:
        if _contains_keyword(normalized_sql, keyword):
            raise Unsafe(
                reason=f"Unsafe SQL operation: {keyword} statement is not allowed. "
                "Only SELECT queries are permitted."
            )

    # Check 3: Reject DML operations inside CTEs
    if reject_cte_with_dml and _has_dml_in_cte(normalized_sql):
        raise Unsafe(
            reason="DML operations (INSERT, UPDATE, DELETE) are not allowed inside CTEs. "
            "Use CTEs only for SELECT queries."
        )

    # Check 4: Custom blocklist patterns
    for pattern in custom_blocklist:
        if _matches_pattern(normalized_sql, pattern):
            raise Unsafe(reason=f"Query matches blocked pattern: {pattern}")

    # Check 5: Reject EXEC, EXECUTE (procedural/dynamic SQL)
    if _contains_keyword(normalized_sql, "EXEC") or _contains_keyword(normalized_sql, "EXECUTE"):
        raise Unsafe(
            reason="Dynamic SQL execution (EXEC/EXECUTE) is not allowed. "
            "Only direct SELECT queries are permitted."
        )

    # Check 6: Reject INTO (output redirection)
    if _contains_keyword(normalized_sql, "INTO") and _is_select_into(normalized_sql):
        raise Unsafe(reason="SELECT INTO is not allowed. Query cannot create or populate tables.")

    # Check 7: Reject UNION with EXCEPT/INTERSECT manipulation
    if _has_union_based_obfuscation(normalized_sql):
        raise Unsafe(reason="Complex UNION patterns with EXCEPT/INTERSECT may be unsafe.")

    # Check 8: the statement itself must be a SELECT or a WITH ... SELECT --
    # this is what makes this gate an *allowlist* rather than a denylist that
    # only blocks verbs someone thought to name, and it is the final catch-all
    # after the checks above, not the first check, so an already-blocked
    # keyword still raises its own specific reason. A denylist alone missed
    # several real, dangerous verbs (COPY, ATTACH, PRAGMA, INSTALL/LOAD, SET)
    # until this was added.
    if not re.match(r"^\s*(SELECT|WITH)\b", normalized_sql, re.IGNORECASE):
        raise Unsafe(
            reason="Only SELECT (optionally with a leading WITH clause) statements are allowed."
        )

    # All checks passed
    return state


def _normalize_sql(sql: str) -> str:
    """Remove comments and normalize whitespace."""
    # Remove line comments (-- comment)
    sql = re.sub(r"--[^\n]*", "", sql)
    # Remove block comments (/* ... */)
    sql = re.sub(r"/\*[\s\S]*?\*/", "", sql)
    # Collapse multiple spaces/newlines into single space
    sql = re.sub(r"\s+", " ", sql)
    return sql.strip()


def _count_sql_statements(sql: str) -> int:
    """
    Count semicolon-delimited SQL statements.
    Heuristic: split by semicolon, filter empty segments.
    """
    # Split by semicolon, ignore trailing empty
    statements = [s.strip() for s in sql.split(";")]
    # Count non-empty statements
    count = sum(1 for s in statements if s)
    return count


def _contains_keyword(sql: str, keyword: str) -> bool:
    """
    Check if SQL contains a keyword.
    Uses word boundary regex to avoid false positives (e.g., 'DROPS' contains 'DROP').
    """
    # Case-insensitive word boundary match
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return re.search(pattern, sql, re.IGNORECASE) is not None


_FILE_OR_NETWORK_READ_RE = re.compile(
    r"\b(read_csv\w*|read_parquet|read_json\w*|read_ndjson\w*|glob|sniff_csv)\s*\(|"
    r"['\"](https?|s3|gcs|gs|azure|hf)://",
    re.IGNORECASE,
)


def _contains_file_or_network_read(sql: str) -> bool:
    """DuckDB table functions (or URL schemes) that read from the filesystem
    or network, usable inside an otherwise-plain SELECT to exfiltrate or read
    arbitrary local/remote data regardless of the connection's `read_only`
    setting."""
    return _FILE_OR_NETWORK_READ_RE.search(sql) is not None


def _has_dml_in_cte(sql: str) -> bool:
    """
    Detect DML (INSERT, UPDATE, DELETE) inside CTEs.
    Pattern: WITH ... AS (...INSERT/UPDATE/DELETE...) SELECT
    """
    # Match WITH clause and check if body contains DML keywords
    cte_pattern = r"WITH\s+\w+\s+AS\s*\(([^)]*)\)"
    matches = re.finditer(cte_pattern, sql, re.IGNORECASE)

    for match in matches:
        cte_body = match.group(1)
        dml_keywords = ["INSERT", "UPDATE", "DELETE"]
        for keyword in dml_keywords:
            if _contains_keyword(cte_body, keyword):
                return True
    return False


def _is_select_into(sql: str) -> bool:
    """
    Detect SELECT INTO pattern (creates new table).
    Pattern: SELECT ... INTO table_name FROM ...
    """
    pattern = r"SELECT\s+.*\s+INTO\s+\w+"
    return re.search(pattern, sql, re.IGNORECASE) is not None


def _has_union_based_obfuscation(sql: str) -> bool:
    """
    Detect potentially unsafe UNION-based patterns.
    Example: complex UNION ALL with EXCEPT to manipulate rows.
    """
    # Check for excessive UNION/EXCEPT/INTERSECT in suspicious patterns
    union_count = len(re.findall(r"\bUNION\b", sql, re.IGNORECASE))
    except_count = len(re.findall(r"\bEXCEPT\b", sql, re.IGNORECASE))
    intersect_count = len(re.findall(r"\bINTERSECT\b", sql, re.IGNORECASE))

    # Flag suspicious: multiple unions with except/intersect (obfuscation)
    if union_count > 2 and (except_count > 0 or intersect_count > 0):
        return True
    return False


def _matches_pattern(sql: str, pattern: str) -> bool:
    """
    Check if SQL matches a custom regex pattern.
    Raises no exception; returns boolean.
    """
    try:
        return re.search(pattern, sql, re.IGNORECASE) is not None
    except re.error:
        # Invalid regex pattern in config
        return False
