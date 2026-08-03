"""Postgres engine adapter: the second EngineAdapter implementation.

Its purpose is to prove the port is a real abstraction rather than a DuckDB
alias. Postgres gives stronger guarantees than DuckDB in two places the kernel
cares about: a genuine per-statement timeout, and a read-only transaction that
the server enforces regardless of what the SQL parser missed.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from omniagent.kernel.ports.engine import (
    EngineCapabilities,
    EngineError,
    ReadOnlyMode,
    ResultTable,
)

# SQLSTATE classes -> kernel error codes. The repair loop branches on the code,
# so the mapping has to stay stable even as psycopg's exception tree changes.
_SQLSTATE_CODES = {
    "42P01": "MISSING_TABLE",
    "42703": "MISSING_COLUMN",
    "42601": "SYNTAX_ERROR",
    "42883": "MISSING_FUNCTION",
    "22P02": "TYPE_ERROR",
    "22003": "TYPE_ERROR",
    "22012": "DIVISION_BY_ZERO",
    "25006": "READ_ONLY_VIOLATION",
    "42501": "PERMISSION_DENIED",
    "57014": "TIMEOUT",
    "53200": "RESOURCE_EXHAUSTED",
    "53300": "RESOURCE_EXHAUSTED",
}


def _to_pyformat(sql: str) -> str:
    """Rewrite the kernel's neutral ``?`` placeholders to psycopg's ``%s``.

    Literal ``%`` in the statement (LIKE patterns, for instance) is doubled so
    psycopg does not read it as the start of its own placeholder.
    """
    out: list[str] = []
    in_string = False
    for char in sql:
        if char == "'":
            in_string = not in_string
            out.append(char)
        elif in_string:
            out.append(char)
        elif char == "%":
            out.append("%%")
        elif char == "?":
            out.append("%s")
        else:
            out.append(char)
    return "".join(out)


class PostgresEngine:
    """Read-only Postgres adapter.

    Every statement runs inside a ``READ ONLY`` transaction that is rolled back
    afterwards, so a write that slipped past the parser still fails at the
    server. ``statement_timeout`` is set per request from the caller's budget.
    """

    dialect = "postgres"

    def __init__(self, dsn: str, *, connect_timeout: int = 10):
        # Imported lazily so the kernel and the DuckDB path stay importable
        # without the postgres extra installed.
        import psycopg

        self._psycopg = psycopg
        self._dsn = dsn
        self._conn = psycopg.connect(dsn, connect_timeout=connect_timeout, autocommit=True)

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            dialect=self.dialect,
            readonly=ReadOnlyMode.NATIVE,
            supports_timeout=True,
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
        """Run a statement in a read-only transaction under a server-side timeout."""
        started = time.perf_counter()
        try:
            with self._conn.transaction():  # rolls back on exit
                with self._conn.cursor() as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
                    cursor.execute("SET LOCAL statement_timeout = %s", (int(timeout_s * 1000),))
                    cursor.execute(_to_pyformat(sql), list(params))
                    columns = tuple(d.name for d in cursor.description or ())
                    rows = cursor.fetchmany(row_cap + 1)
        except Exception as exc:
            raise self.normalize_error(exc) from exc
        finally:
            elapsed_ms = int((time.perf_counter() - started) * 1000)

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
        """Table and column metadata for schema linking."""
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position
                """,
                (dataset_id,),
            )
            rows = cursor.fetchall()

        tables: dict[str, list[dict[str, str]]] = {}
        for table_name, column_name, data_type in rows:
            tables.setdefault(table_name, []).append({"name": column_name, "type": data_type})
        return {"dataset_id": dataset_id, "tables": tables}

    def normalize_error(self, exc: Exception) -> EngineError:
        """Map a Postgres SQLSTATE onto the same codes the DuckDB adapter emits."""
        if isinstance(exc, EngineError):
            return exc

        sqlstate = getattr(exc, "sqlstate", None)
        message = str(exc)
        if sqlstate and sqlstate in _SQLSTATE_CODES:
            return EngineError(_SQLSTATE_CODES[sqlstate], message)
        if isinstance(exc, self._psycopg.OperationalError):
            return EngineError("CONNECTION_ERROR", message)
        return EngineError("ENGINE_ERROR", message)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PostgresEngine:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
