"""Conformance tests for DuckDBVSSStore against the VectorStore port."""

import pytest

from omniagent.adapters.vectors import DuckDBVSSStore
from omniagent.kernel.ports.identity import Scope
from omniagent.kernel.ports.stores import Namespace

_DIM = 4


def _vec(*components: float) -> list[float]:
    return list(components)


@pytest.fixture
def store():
    with DuckDBVSSStore(dim=_DIM) as s:
        yield s


@pytest.fixture
def ns():
    return Namespace(
        kind="verified", scope=Scope(tenant="acme", dataset="ecommerce", schema_version="v1")
    )


@pytest.mark.contract
class TestDuckDBVSSStoreConformance:
    def test_search_ranks_by_cosine_similarity(self, store, ns):
        store.upsert(
            ns,
            [
                {
                    "id": "close",
                    "vector": _vec(1.0, 0.0, 0.0, 0.0),
                    "text": "close",
                    "metadata": {},
                },
                {
                    "id": "orthogonal",
                    "vector": _vec(0.0, 1.0, 0.0, 0.0),
                    "text": "orthogonal",
                    "metadata": {},
                },
                {
                    "id": "opposite",
                    "vector": _vec(-1.0, 0.0, 0.0, 0.0),
                    "text": "opposite",
                    "metadata": {},
                },
            ],
        )
        results = store.search(ns, _vec(1.0, 0.0, 0.0, 0.0), k=3)
        assert [r["id"] for r in results] == ["close", "orthogonal", "opposite"]
        assert results[0]["score"] == pytest.approx(1.0)
        assert results[1]["score"] == pytest.approx(0.0, abs=1e-6)
        assert results[2]["score"] == pytest.approx(-1.0)

    def test_search_respects_k(self, store, ns):
        store.upsert(
            ns,
            [
                {"id": str(i), "vector": _vec(1.0, 0.0, 0.0, 0.0), "text": str(i), "metadata": {}}
                for i in range(5)
            ],
        )
        results = store.search(ns, _vec(1.0, 0.0, 0.0, 0.0), k=2)
        assert len(results) == 2

    def test_namespace_isolation(self, store):
        ns_a = Namespace(
            kind="verified", scope=Scope(tenant="acme", dataset="ecommerce", schema_version="v1")
        )
        ns_b = Namespace(
            kind="verified", scope=Scope(tenant="acme", dataset="ecommerce", schema_version="v2")
        )
        store.upsert(
            ns_a,
            [{"id": "only-in-a", "vector": _vec(1.0, 0.0, 0.0, 0.0), "text": "a", "metadata": {}}],
        )
        assert store.search(ns_b, _vec(1.0, 0.0, 0.0, 0.0), k=5) == []
        results_a = store.search(ns_a, _vec(1.0, 0.0, 0.0, 0.0), k=5)
        assert len(results_a) == 1
        assert results_a[0]["id"] == "only-in-a"

    def test_where_filters_by_metadata(self, store, ns):
        store.upsert(
            ns,
            [
                {
                    "id": "a",
                    "vector": _vec(1.0, 0.0, 0.0, 0.0),
                    "text": "a",
                    "metadata": {"status": "approved"},
                },
                {
                    "id": "b",
                    "vector": _vec(1.0, 0.0, 0.0, 0.0),
                    "text": "b",
                    "metadata": {"status": "proposed"},
                },
            ],
        )
        results = store.search(ns, _vec(1.0, 0.0, 0.0, 0.0), k=5, where={"status": "approved"})
        assert [r["id"] for r in results] == ["a"]

    def test_upsert_same_id_overwrites(self, store, ns):
        store.upsert(
            ns, [{"id": "x", "vector": _vec(1.0, 0.0, 0.0, 0.0), "text": "first", "metadata": {}}]
        )
        store.upsert(
            ns, [{"id": "x", "vector": _vec(0.0, 1.0, 0.0, 0.0), "text": "second", "metadata": {}}]
        )
        results = store.search(ns, _vec(0.0, 1.0, 0.0, 0.0), k=5)
        assert len(results) == 1
        assert results[0]["text"] == "second"
        assert results[0]["score"] == pytest.approx(1.0)

    def test_count_reflects_namespace_only(self, store):
        ns_a = Namespace(
            kind="verified", scope=Scope(tenant="acme", dataset="ecommerce", schema_version="v1")
        )
        ns_b = Namespace(
            kind="verified", scope=Scope(tenant="acme", dataset="ecommerce", schema_version="v2")
        )
        store.upsert(
            ns_a,
            [
                {"id": str(i), "vector": _vec(1.0, 0.0, 0.0, 0.0), "text": str(i), "metadata": {}}
                for i in range(3)
            ],
        )
        assert store.count(ns_a) == 3
        assert store.count(ns_b) == 0

    def test_drop_removes_only_its_namespace(self, store):
        ns_a = Namespace(
            kind="verified", scope=Scope(tenant="acme", dataset="ecommerce", schema_version="v1")
        )
        ns_b = Namespace(
            kind="verified", scope=Scope(tenant="acme", dataset="ecommerce", schema_version="v2")
        )
        store.upsert(
            ns_a, [{"id": "a", "vector": _vec(1.0, 0.0, 0.0, 0.0), "text": "a", "metadata": {}}]
        )
        store.upsert(
            ns_b, [{"id": "b", "vector": _vec(1.0, 0.0, 0.0, 0.0), "text": "b", "metadata": {}}]
        )
        store.drop(ns_a)
        assert store.count(ns_a) == 0
        assert store.count(ns_b) == 1
