"""Conformance tests for DuckDBValueDictionary: filter-value grounding.

Uses the real FastEmbedProvider and the shared `ecommerce_warehouse` fixture
(a real DuckDB engine), since the whole point of this component is genuine
embedding-similarity behavior against genuine query results — a fake embedder
would validate nothing about whether grounding actually works.
"""

import pytest

from omniagent.adapters.embeddings import FastEmbedProvider
from omniagent.adapters.vectors import DuckDBVSSStore
from omniagent.kernel.ports.identity import Scope
from omniagent.memory.value_dictionary import DuckDBValueDictionary

# See test_verified_queries.py's pytestmark comment: shared xdist_group so
# concurrent workers don't race to load the real embedding model at once.
pytestmark = [pytest.mark.contract, pytest.mark.xdist_group(name="fastembed")]


@pytest.fixture(scope="module")
def embedder():
    return FastEmbedProvider()


@pytest.fixture
def value_dict(embedder):
    with DuckDBVSSStore(dim=embedder.dim) as vstore:
        yield DuckDBValueDictionary(vstore, embedder)


@pytest.fixture
def scope():
    return Scope(tenant="acme", dataset="ecommerce", schema_version="hash-v1")


class TestDuckDBValueDictionaryConformance:
    def test_index_returns_distinct_value_count(self, value_dict, ecommerce_warehouse, scope):
        count = value_dict.index(
            scope, ecommerce_warehouse, table="ecommerce_customers", column="region"
        )
        assert count == 3  # West, East, London -- see conftest.ecommerce_warehouse docstring

    def test_ground_finds_exact_value(self, value_dict, ecommerce_warehouse, scope):
        value_dict.index(scope, ecommerce_warehouse, table="ecommerce_customers", column="region")
        matches = value_dict.ground(
            scope, table="ecommerce_customers", column="region", phrase="London"
        )
        assert matches[0][0] == "London"
        assert matches[0][1] == pytest.approx(1.0, abs=1e-4)

    def test_ground_finds_paraphrase(self, value_dict, ecommerce_warehouse, scope):
        value_dict.index(scope, ecommerce_warehouse, table="ecommerce_customers", column="region")
        matches = value_dict.ground(
            scope, table="ecommerce_customers", column="region", phrase="west coast"
        )
        assert matches[0][0] == "West"

    def test_ground_rejects_unrelated_phrase(self, value_dict, ecommerce_warehouse, scope):
        value_dict.index(scope, ecommerce_warehouse, table="ecommerce_customers", column="region")
        assert (
            value_dict.ground(
                scope, table="ecommerce_customers", column="region", phrase="banana smoothie"
            )
            == []
        )

    def test_ground_scoped_to_indexed_column(self, value_dict, ecommerce_warehouse, scope):
        value_dict.index(scope, ecommerce_warehouse, table="ecommerce_customers", column="region")
        value_dict.index(scope, ecommerce_warehouse, table="ecommerce_customers", column="country")
        region_matches = value_dict.ground(
            scope, table="ecommerce_customers", column="region", phrase="US"
        )
        assert "US" not in [m[0] for m in region_matches]
        country_matches = value_dict.ground(
            scope, table="ecommerce_customers", column="country", phrase="US"
        )
        assert country_matches[0][0] == "US"

    def test_index_isolated_by_schema_version(self, value_dict, ecommerce_warehouse, scope):
        value_dict.index(scope, ecommerce_warehouse, table="ecommerce_customers", column="region")
        other_scope = Scope(tenant=scope.tenant, dataset=scope.dataset, schema_version="hash-v2")
        assert (
            value_dict.ground(
                other_scope, table="ecommerce_customers", column="region", phrase="London"
            )
            == []
        )

    def test_reindex_upserts_without_duplicates(self, value_dict, ecommerce_warehouse, scope):
        value_dict.index(scope, ecommerce_warehouse, table="ecommerce_customers", column="region")
        count = value_dict.index(
            scope, ecommerce_warehouse, table="ecommerce_customers", column="region"
        )
        assert count == 3
        matches = value_dict.ground(
            scope, table="ecommerce_customers", column="region", phrase="London", k=10
        )
        assert [m[0] for m in matches].count("London") == 1
