"""DuckDB-backed vector store: embedding storage and cosine-similarity search.

At this project's expected scale (hundreds of verified queries per tenant,
not millions), brute-force `array_cosine_similarity` over a namespace-
filtered scan is simpler and more correct than standing up an HNSW index,
so that is what search() actually does. The VSS extension is still
installed and loaded — it is what makes `array_cosine_similarity` and the
FLOAT[] array type efficient in DuckDB — but its ANN index is deliberately
not required for correctness here; the file name and the extension it
loads describe the acceleration path, not something every namespace at
this project's scale needs to pay for.

Embedding generation itself (fastembed) happens at the call site, not
here — this class only stores and searches vectors that already exist,
matching the port's `search(ns, query_vec, ...)` signature (a vector in,
not text).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from omniagent.kernel.ports.stores import Namespace


class DuckDBVSSStore:
    """VectorStore implementation over an embedded DuckDB file."""

    def __init__(self, database: str | Path = ":memory:", *, dim: int = 384):
        self._dim = dim
        self._conn = duckdb.connect(str(database))
        self._conn.execute("INSTALL vss")
        self._conn.execute("LOAD vss")
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS vector_docs (
                id VARCHAR NOT NULL,
                ns_kind VARCHAR NOT NULL,
                ns_tenant VARCHAR NOT NULL,
                ns_dataset VARCHAR NOT NULL,
                ns_schema_version VARCHAR NOT NULL,
                vector FLOAT[{dim}] NOT NULL,
                text VARCHAR,
                metadata VARCHAR,
                PRIMARY KEY (ns_kind, ns_tenant, ns_dataset, ns_schema_version, id)
            )
        """)

    def upsert(self, ns: Namespace, docs: Any) -> None:
        """Insert or update vectors. Each doc is a dict with keys id, vector,
        text (optional), metadata (optional dict, JSON-serialized)."""
        scope = ns.scope
        for doc in docs:
            metadata_json = json.dumps(doc.get("metadata") or {})
            self._conn.execute(
                """
                INSERT INTO vector_docs
                    (id, ns_kind, ns_tenant, ns_dataset, ns_schema_version, vector, text, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (ns_kind, ns_tenant, ns_dataset, ns_schema_version, id)
                DO UPDATE SET vector = excluded.vector, text = excluded.text,
                              metadata = excluded.metadata
                """,
                [
                    doc["id"],
                    ns.kind,
                    scope.tenant,
                    scope.dataset,
                    scope.schema_version,
                    list(doc["vector"]),
                    doc.get("text"),
                    metadata_json,
                ],
            )

    def search(
        self, ns: Namespace, query_vec: Any, k: int, where: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        scope = ns.scope
        conditions = [
            "ns_kind = ?",
            "ns_tenant = ?",
            "ns_dataset = ?",
            "ns_schema_version = ?",
        ]
        params: list[Any] = [ns.kind, scope.tenant, scope.dataset, scope.schema_version]

        for key, value in (where or {}).items():
            conditions.append("json_extract_string(metadata, '$.' || ?) = ?")
            params.extend([key, str(value)])

        # S608 suppressed below: interpolated pieces are self._dim (a constructor-set
        # int, not user input) and `conditions`, which only ever holds fixed column-name
        # clauses from this method's own code; every actual value is bound via `params`/`?`.
        query = f"""
            SELECT id, text, metadata, array_cosine_similarity(vector, ?::FLOAT[{self._dim}]) AS score
            FROM vector_docs
            WHERE {" AND ".join(conditions)}
            ORDER BY score DESC
            LIMIT ?
        """  # noqa: S608
        rows = self._conn.execute(query, [list(query_vec), *params, k]).fetchall()
        return [
            {"id": row[0], "text": row[1], "metadata": json.loads(row[2] or "{}"), "score": row[3]}
            for row in rows
        ]

    def drop(self, ns: Namespace) -> None:
        scope = ns.scope
        self._conn.execute(
            """
            DELETE FROM vector_docs
            WHERE ns_kind = ? AND ns_tenant = ? AND ns_dataset = ? AND ns_schema_version = ?
            """,
            [ns.kind, scope.tenant, scope.dataset, scope.schema_version],
        )

    def count(self, ns: Namespace) -> int:
        scope = ns.scope
        row = self._conn.execute(
            """
            SELECT COUNT(*) FROM vector_docs
            WHERE ns_kind = ? AND ns_tenant = ? AND ns_dataset = ? AND ns_schema_version = ?
            """,
            [ns.kind, scope.tenant, scope.dataset, scope.schema_version],
        ).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> DuckDBVSSStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
