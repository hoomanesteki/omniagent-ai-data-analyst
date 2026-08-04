"""DuckDB engine adapter: read-only execution with a fresh cursor per request."""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb

from omniagent.kernel.ports.engine import (
    EngineCapabilities,
    EngineError,
    ReadOnlyMode,
    ResultTable,
)

# DuckDB surfaces the offending identifier in the message body, not in a field.
_MISSING_TABLE = re.compile(r"table with name (\S+) does not exist", re.IGNORECASE)
_MISSING_COLUMN = re.compile(r'referenced column "([^"]+)" not found', re.IGNORECASE)
_BINDER_COLUMN = re.compile(r"column \"?([\w.]+)\"? not found", re.IGNORECASE)


def _prefix_like_pattern(dataset_id: str) -> str:
    """`dataset_id` as a LIKE prefix pattern, with its own `%`/`_`/`\\` escaped."""
    escaped = dataset_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}\\_%"


class DuckDBEngine:
    """Read-only DuckDB adapter.

    The connection is opened with ``read_only=True`` so the engine itself, not
    only the SQL parser, refuses writes. Each ``execute`` takes a fresh cursor
    so concurrent requests cannot observe one another's partial result sets.
    """

    dialect = "duckdb"

    def __init__(self, database: str | Path = ":memory:", *, read_only: bool | None = None):
        self._database = str(database)
        # An in-memory database cannot be opened read-only: there is nothing to
        # open. The parser and the gate stack are the wall in that case.
        if read_only is None:
            read_only = self._database != ":memory:"
        self._read_only = read_only
        self._conn = duckdb.connect(self._database, read_only=read_only)

    @property
    def database_path(self) -> str:
        """The path (or ``":memory:"``) this engine was opened against, for
        the rare caller that genuinely needs the underlying file rather than
        a query result -- e.g. a tool that copies the warehouse elsewhere
        before running something the gate stack itself would refuse."""
        return self._database

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            dialect=self.dialect,
            readonly=ReadOnlyMode.NATIVE if self._read_only else ReadOnlyMode.VALIDATED_ONLY,
            supports_timeout=False,
            supports_cancel=True,
        )

    def execute(
        self,
        sql: str,
        *,
        params: Sequence[Any] = (),
        principal: Any = None,
        timeout_s: float = 30.0,
        row_cap: int = 10_000,
    ) -> ResultTable:
        """Run a read-only statement, capping rows and reporting truncation.

        One extra row beyond ``row_cap`` is fetched so truncation is detected
        exactly rather than inferred from a full page.
        """
        cursor = self._conn.cursor()
        started = time.perf_counter()
        try:
            cursor.execute(sql, list(params))
            columns = tuple(d[0] for d in cursor.description or ())
            rows = cursor.fetchmany(row_cap + 1)
        except Exception as exc:  # normalized below for the repair loop
            raise self.normalize_error(exc) from exc
        finally:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            cursor.close()

        truncated = len(rows) > row_cap
        if truncated:
            rows = rows[:row_cap]

        return ResultTable(
            columns=columns,
            arrow_schema=None,
            batches=rows,
            row_count=len(rows),
            truncated=truncated,
            elapsed_ms=elapsed_ms,
        )

    def schema_snapshot(self, dataset_id: str) -> dict[str, Any]:
        """Table and column metadata for schema linking.

        Every pack's tables live together in one flat warehouse (see
        scripts/load_warehouse.py), disambiguated by a `{dataset_id}_` table
        name prefix rather than a DuckDB schema per dataset — `ecommerce_orders`,
        `saas_accounts`, and so on, all in the default `main` schema. So the
        dataset boundary here is a name-prefix filter, not `table_schema`.
        """
        cursor = self._conn.cursor()
        try:
            rows = cursor.execute(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_name LIKE ? ESCAPE '\\'
                ORDER BY table_name, ordinal_position
                """,
                [_prefix_like_pattern(dataset_id)],
            ).fetchall()
        finally:
            cursor.close()

        tables: dict[str, list[dict[str, str]]] = {}
        for table_name, column_name, data_type in rows:
            tables.setdefault(table_name, []).append({"name": column_name, "type": data_type})
        return {"dataset_id": dataset_id, "tables": tables}

    def normalize_error(self, exc: Exception) -> EngineError:
        """Map a DuckDB error onto a stable code the repair loop can branch on."""
        if isinstance(exc, EngineError):
            return exc
        message = str(exc)

        if isinstance(exc, duckdb.CatalogException):
            if _MISSING_TABLE.search(message):
                return EngineError("MISSING_TABLE", message)
            return EngineError("MISSING_OBJECT", message)
        if isinstance(exc, duckdb.BinderException):
            if _MISSING_COLUMN.search(message) or _BINDER_COLUMN.search(message):
                return EngineError("MISSING_COLUMN", message)
            return EngineError("BINDER_ERROR", message)
        if isinstance(exc, duckdb.ParserException):
            return EngineError("SYNTAX_ERROR", message)
        if isinstance(exc, duckdb.ConversionException):
            return EngineError("TYPE_ERROR", message)
        if isinstance(exc, duckdb.PermissionException):
            return EngineError("READ_ONLY_VIOLATION", message)
        if isinstance(exc, duckdb.OutOfMemoryException):
            return EngineError("RESOURCE_EXHAUSTED", message)
        return EngineError("ENGINE_ERROR", message)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> DuckDBEngine:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
