"""DuckDB-backed answer ledger: a durable, queryable audit table.

Chosen for the same reason DuckDB backs the vector store and the verified
query cache elsewhere in this project: a single embedded file, zero server
to run, and SQL for whoever needs to query the audit trail directly
(compliance review, debugging a specific thread) without a bespoke tool.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from omniagent.kernel.ports.ledger import LedgerEntry


class DuckDBAnswerLedger:
    """AnswerLedgerStore implementation over an embedded DuckDB file."""

    def __init__(self, database: str | Path = ":memory:"):
        self._conn = duckdb.connect(str(database))
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS answer_ledger (
                trace_id VARCHAR PRIMARY KEY,
                thread_id VARCHAR NOT NULL,
                dataset_id VARCHAR NOT NULL,
                question VARCHAR,
                route VARCHAR,
                matched_metric VARCHAR,
                executed_sql VARCHAR,
                confidence DOUBLE,
                error VARCHAR,
                created_at TIMESTAMP NOT NULL
            )
        """)

    def record(self, entry: LedgerEntry) -> None:
        self._conn.execute(
            """
            INSERT INTO answer_ledger
                (trace_id, thread_id, dataset_id, question, route, matched_metric,
                 executed_sql, confidence, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                entry.trace_id,
                entry.thread_id,
                entry.dataset_id,
                entry.question,
                entry.route,
                entry.matched_metric,
                entry.executed_sql,
                entry.confidence,
                entry.error,
                entry.created_at,
            ],
        )

    def for_thread(self, thread_id: str) -> list[LedgerEntry]:
        rows = self._conn.execute(
            """
            SELECT trace_id, thread_id, dataset_id, question, route, matched_metric,
                   executed_sql, confidence, error, created_at
            FROM answer_ledger
            WHERE thread_id = ?
            ORDER BY created_at
            """,
            [thread_id],
        ).fetchall()
        return [LedgerEntry(*row) for row in rows]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> DuckDBAnswerLedger:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
