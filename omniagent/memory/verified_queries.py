"""VerifiedQueryStore: approved question-to-query pairs, retrieved by semantic similarity.

Storage is namespaced by (tenant, dataset, schema_version) via `Namespace`/`Scope`
(see kernel/ports/stores.py), so a schema-version bump alone already makes prior
verified queries unreachable through `retrieve()` — a different schema_version is
a different namespace, not a filtered subset of the same one. `invalidate()` is
therefore a storage-reclamation operation, not a correctness requirement: it
purges a specific, now-superseded schema_version's entries so they stop occupying
space. `schema_version` is documented on `Scope` as an opaque manifest hash, not a
sequence number, so there is no `<` ordering to apply — `older_than_version` is
taken to name the exact stale version the caller wants purged (the migration that
bumps the schema knows the hash it is retiring).

`retrieve()` applies `min_score` purely to reject obviously-unrelated candidates
(measured empirically: unrelated questions score ~0.45-0.50 cosine similarity
against bge-small-en-v1.5 embeddings, genuine paraphrases score ~0.65-0.98). It
does NOT guarantee the top hit answers the *same* question as asked — a
same-shape, different-metric near miss ("total revenue by region" vs. "total
customers by region") can score higher (~0.87) than a genuine paraphrase of a
different, unrelated verified query. A caller that wants to serve a retrieved
artifact without re-deriving it must additionally cross-check the artifact's
metric/dimensions against a fresh deterministic catalog match on the incoming
question — that check belongs to the fast-path wiring, not this store.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from omniagent.kernel.ports.embeddings import Embedder
from omniagent.kernel.ports.identity import Scope
from omniagent.kernel.ports.stores import Namespace, VectorStore, VerifiedQuery

_STATUS_RANK = {"proposed": 0, "approved": 1, "trusted": 2}
_NS_KIND = "verified"
_DEFAULT_MIN_SCORE = 0.5


class DuckDBVerifiedQueryStore:
    """VerifiedQueryStore implementation: embeds questions, delegates storage/search."""

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

    def add(self, scope: Scope, item: VerifiedQuery) -> None:
        ns = Namespace(kind=_NS_KIND, scope=scope)
        vector = self._embedder.embed([item.question])[0]
        doc_id = hashlib.sha256(item.question.strip().lower().encode()).hexdigest()[:16]
        artifact_is_json = not isinstance(item.artifact, str)
        artifact_text = json.dumps(item.artifact) if artifact_is_json else item.artifact
        metadata = {
            "artifact": artifact_text,
            "artifact_is_json": artifact_is_json,
            "result_signature": item.result_signature,
            "status": item.status,
            "approved_by": item.approved_by,
            "created_at": item.created_at.isoformat(),
        }
        self._store.upsert(
            ns, [{"id": doc_id, "vector": vector, "text": item.question, "metadata": metadata}]
        )

    def retrieve(
        self, scope: Scope, question: str, k: int = 5, min_status: str = "approved"
    ) -> list[VerifiedQuery]:
        ns = Namespace(kind=_NS_KIND, scope=scope)
        vector = self._embedder.embed([question])[0]
        min_rank = _STATUS_RANK[min_status]
        results = self._store.search(ns, vector, k=k)
        out: list[VerifiedQuery] = []
        for row in results:
            if row["score"] < self._min_score:
                continue
            meta = row["metadata"]
            if _STATUS_RANK.get(meta["status"], -1) < min_rank:
                continue
            artifact: str | dict[str, object]
            artifact = (
                json.loads(meta["artifact"]) if meta["artifact_is_json"] else meta["artifact"]
            )
            out.append(
                VerifiedQuery(
                    question=row["text"],
                    artifact=artifact,
                    result_signature=meta["result_signature"],
                    status=meta["status"],
                    approved_by=meta["approved_by"],
                    created_at=datetime.fromisoformat(meta["created_at"]),
                )
            )
        return out

    def invalidate(self, tenant: str, dataset: str, older_than_version: str) -> int:
        ns = Namespace(
            kind=_NS_KIND,
            scope=Scope(tenant=tenant, dataset=dataset, schema_version=older_than_version),
        )
        count = self._store.count(ns)
        self._store.drop(ns)
        return count
