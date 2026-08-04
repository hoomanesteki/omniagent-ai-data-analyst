"""ValueDictionary: grounds free-text filter phrases to actual stored column values.

Guards against a classic text-to-SQL failure mode: a generated filter value that
sounds plausible ("CA") but does not match what is actually stored ("California",
"US-CA", ...). `index()` embeds every distinct value of a chosen table/column pair
once (typically at pack install time); `ground()` embeds an incoming phrase and
returns the closest values that genuinely exist in that column, so a caller binds
a value guaranteed to be real rather than one an LLM invented.

`table`/`column` are interpolated into the SQL text rather than bound as params,
which is safe here only because both always come from the pack's own trusted
schema config (see `EngineAdapter.schema_snapshot`), never from a model or an end
user — the same trust boundary `native_yaml.py`'s compiler relies on elsewhere.
"""

from __future__ import annotations

import hashlib
from typing import Any

from omniagent.kernel.ports.embeddings import Embedder
from omniagent.kernel.ports.engine import EngineAdapter
from omniagent.kernel.ports.identity import Scope
from omniagent.kernel.ports.stores import Namespace, VectorStore

_NS_KIND = "values"
_DEFAULT_MIN_SCORE = 0.5


class DuckDBValueDictionary:
    """Distinct-value index for grounding filter phrases to real column values."""

    def __init__(
        self,
        vector_store: VectorStore,
        embedder: Embedder,
        *,
        min_score: float = _DEFAULT_MIN_SCORE,
    ):
        self._store = vector_store
        self._embedder = embedder
        self._min_score = min_score

    def index(
        self,
        scope: Scope,
        engine: EngineAdapter,
        *,
        table: str,
        column: str,
        principal: Any = None,
        max_values: int = 1000,
    ) -> int:
        """Embed every distinct non-null value of table.column. Returns count indexed."""
        result = engine.execute(
            f'SELECT DISTINCT "{column}" AS v FROM "{table}" WHERE "{column}" IS NOT NULL',  # noqa: S608
            principal=principal,
            timeout_s=10.0,
            row_cap=max_values,
        )
        values = [str(row[0]) for row in result.batches]
        if not values:
            return 0

        vectors = self._embedder.embed(values)
        ns = Namespace(kind=_NS_KIND, scope=scope)
        docs = [
            {
                "id": hashlib.sha256(f"{table}.{column}={value}".encode()).hexdigest()[:16],
                "vector": vector,
                "text": value,
                "metadata": {"table": table, "column": column},
            }
            for value, vector in zip(values, vectors, strict=True)
        ]
        self._store.upsert(ns, docs)
        return len(docs)

    def ground(
        self, scope: Scope, *, table: str, column: str, phrase: str, k: int = 3
    ) -> list[tuple[str, float]]:
        """Return the closest real values of table.column to `phrase`, best first."""
        ns = Namespace(kind=_NS_KIND, scope=scope)
        vector = self._embedder.embed([phrase])[0]
        results = self._store.search(ns, vector, k=k, where={"table": table, "column": column})
        return [(row["text"], row["score"]) for row in results if row["score"] >= self._min_score]
