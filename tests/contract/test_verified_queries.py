"""Conformance tests for DuckDBVerifiedQueryStore against the VerifiedQueryStore port.

Uses the real FastEmbedProvider (a local ONNX model, no API key, no network at
test time once the model is cached) rather than a fake, since embedding
similarity behavior — the whole point of this store — cannot be faked
meaningfully; see the module docstring in verified_queries.py for the
empirically measured score ranges these tests rely on.
"""

from datetime import UTC, datetime

import pytest

from omniagent.adapters.embeddings import FastEmbedProvider
from omniagent.adapters.vectors import DuckDBVSSStore
from omniagent.kernel.ports.identity import Scope
from omniagent.kernel.ports.stores import VerifiedQuery
from omniagent.memory.verified_queries import DuckDBVerifiedQueryStore

# xdist_group: every module that constructs a real FastEmbedProvider shares
# this group so pytest-xdist (run with --dist=loadgroup) serializes them onto
# one worker instead of letting several workers load onnxruntime + the model
# into memory at the same moment -- observed to crash a worker process
# outright on a memory-constrained runner, not just slow things down.
pytestmark = [pytest.mark.contract, pytest.mark.xdist_group(name="fastembed")]


@pytest.fixture(scope="module")
def embedder():
    return FastEmbedProvider()


@pytest.fixture
def store(embedder):
    with DuckDBVSSStore(dim=embedder.dim) as vstore:
        yield DuckDBVerifiedQueryStore(vstore, embedder)


@pytest.fixture
def scope():
    return Scope(tenant="acme", dataset="ecommerce", schema_version="hash-v1")


def _item(question, artifact, *, status="approved", signature="sig") -> VerifiedQuery:
    return VerifiedQuery(
        question=question,
        artifact=artifact,
        result_signature=signature,
        status=status,
        approved_by="hooman",
        created_at=datetime.now(UTC),
    )


class TestDuckDBVerifiedQueryStoreConformance:
    def test_retrieve_finds_paraphrase(self, store, scope):
        store.add(
            scope,
            _item(
                "what was net revenue last quarter",
                {"metric": "net_revenue", "time_range": "last_quarter"},
                signature="sig-1",
            ),
        )
        results = store.retrieve(scope, "net revenue for last quarter", k=5)
        assert len(results) == 1
        assert results[0].result_signature == "sig-1"
        assert results[0].artifact == {"metric": "net_revenue", "time_range": "last_quarter"}

    def test_retrieve_preserves_string_artifact(self, store, scope):
        store.add(
            scope,
            _item(
                "total customers by region",
                "SELECT region, count(*) FROM customers GROUP BY region",
                signature="sig-2",
            ),
        )
        results = store.retrieve(scope, "total customers by region", k=5)
        assert results[0].artifact == "SELECT region, count(*) FROM customers GROUP BY region"

    def test_retrieve_filters_by_min_status(self, store, scope):
        store.add(
            scope,
            _item("total customers by region", "SELECT ...", status="proposed", signature="sig-3"),
        )
        assert store.retrieve(scope, "total customers by region", k=5, min_status="approved") == []
        proposed_results = store.retrieve(
            scope, "total customers by region", k=5, min_status="proposed"
        )
        assert len(proposed_results) == 1
        assert proposed_results[0].result_signature == "sig-3"

    def test_retrieve_rejects_unrelated_question_via_min_score(self, store, scope):
        store.add(
            scope,
            _item(
                "what was net revenue last quarter", {"metric": "net_revenue"}, signature="sig-4"
            ),
        )
        assert store.retrieve(scope, "what is the weather in paris today", k=5) == []

    def test_retrieve_isolated_by_schema_version(self, store, scope):
        store.add(
            scope, _item("net revenue last quarter", {"metric": "net_revenue"}, signature="sig-5")
        )
        other_scope = Scope(tenant=scope.tenant, dataset=scope.dataset, schema_version="hash-v2")
        assert store.retrieve(other_scope, "net revenue last quarter", k=5) == []

    def test_add_same_question_upserts(self, store, scope):
        store.add(
            scope, _item("net revenue last quarter", {"metric": "net_revenue"}, signature="sig-old")
        )
        store.add(
            scope,
            _item("net revenue last quarter", {"metric": "net_revenue_v2"}, signature="sig-new"),
        )
        results = store.retrieve(scope, "net revenue last quarter", k=5)
        assert len(results) == 1
        assert results[0].result_signature == "sig-new"

    def test_invalidate_purges_named_version_and_returns_count(self, store, scope):
        store.add(
            scope, _item("net revenue last quarter", {"metric": "net_revenue"}, signature="sig-6")
        )
        store.add(scope, _item("total customers by region", "SELECT ...", signature="sig-7"))

        count = store.invalidate(scope.tenant, scope.dataset, scope.schema_version)

        assert count == 2
        assert store.retrieve(scope, "net revenue last quarter", k=5) == []

    def test_invalidate_is_idempotent(self, store, scope):
        store.add(
            scope, _item("net revenue last quarter", {"metric": "net_revenue"}, signature="sig-8")
        )
        store.invalidate(scope.tenant, scope.dataset, scope.schema_version)
        assert store.invalidate(scope.tenant, scope.dataset, scope.schema_version) == 0

    def test_invalidate_does_not_touch_other_versions(self, store, scope):
        store.add(
            scope, _item("net revenue last quarter", {"metric": "net_revenue"}, signature="sig-9")
        )
        other_scope = Scope(tenant=scope.tenant, dataset=scope.dataset, schema_version="hash-v2")
        store.add(
            other_scope,
            _item("net revenue last quarter", {"metric": "net_revenue"}, signature="sig-10"),
        )

        store.invalidate(scope.tenant, scope.dataset, scope.schema_version)

        assert (
            store.retrieve(other_scope, "net revenue last quarter", k=5)[0].result_signature
            == "sig-10"
        )
