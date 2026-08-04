"""Conformance tests for generate_golden_set: real pack, real DuckDB warehouse.

Ground truth in every generated item comes from actually compiling and
executing the query against the shared, hand-computed `ecommerce_warehouse`
fixture (tests/conftest.py) -- the exact same numbers every other
component/integration test already hand-verifies for this fixture, so
these tests check the *generator's* correctness (right count, right
metric/dimension attached, real SQL, real rows), not the numbers again.
"""

import pytest

from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
from omniagent.eval.goldgen import generate_golden_set


@pytest.fixture
def provider():
    return NativeYamlProvider("packs")


@pytest.mark.contract
class TestGenerateGoldenSet:
    def test_generates_at_least_one_item_per_metric(self, provider, ecommerce_warehouse):
        catalog = provider.catalog("ecommerce")
        items = generate_golden_set(
            dataset_id="ecommerce",
            catalog=catalog,
            semantic_provider=provider,
            engine=ecommerce_warehouse,
        )

        covered_metrics = {item.expected_metric for item in items}
        assert covered_metrics == set(catalog.metric_names())

    def test_single_metric_items_have_real_compiled_sql_and_ground_truth(
        self, provider, ecommerce_warehouse
    ):
        catalog = provider.catalog("ecommerce")
        items = generate_golden_set(
            dataset_id="ecommerce",
            catalog=catalog,
            semantic_provider=provider,
            engine=ecommerce_warehouse,
        )

        gross_revenue_items = [
            item
            for item in items
            if item.expected_metric == "gross_revenue" and item.category == "single_metric"
        ]
        assert len(gross_revenue_items) == 4  # one per single-metric template
        assert all("SELECT" in item.gold_sql.upper() for item in gross_revenue_items)
        assert all(item.gold_result == [{"gross_revenue": 225.0}] for item in gross_revenue_items)
        assert all(item.expected_group_by == () for item in gross_revenue_items)

    def test_breakdown_items_carry_the_actual_grouped_rows(self, provider, ecommerce_warehouse):
        catalog = provider.catalog("ecommerce")
        items = generate_golden_set(
            dataset_id="ecommerce",
            catalog=catalog,
            semantic_provider=provider,
            engine=ecommerce_warehouse,
        )

        breakdown_items = [
            item
            for item in items
            if item.expected_metric == "gross_revenue" and item.category == "breakdown"
        ]
        assert breakdown_items
        assert all(len(item.expected_group_by) == 1 for item in breakdown_items)
        assert all(len(item.gold_result) >= 1 for item in breakdown_items)

    def test_item_ids_are_unique(self, provider, ecommerce_warehouse):
        catalog = provider.catalog("ecommerce")
        items = generate_golden_set(
            dataset_id="ecommerce",
            catalog=catalog,
            semantic_provider=provider,
            engine=ecommerce_warehouse,
        )

        item_ids = [item.item_id for item in items]
        assert len(item_ids) == len(set(item_ids))

    def test_questions_are_all_distinct_phrasings(self, provider, ecommerce_warehouse):
        catalog = provider.catalog("ecommerce")
        items = generate_golden_set(
            dataset_id="ecommerce",
            catalog=catalog,
            semantic_provider=provider,
            engine=ecommerce_warehouse,
        )

        net_revenue_questions = [
            item.question for item in items if item.expected_metric == "net_revenue"
        ]
        assert len(net_revenue_questions) == len(set(net_revenue_questions))
