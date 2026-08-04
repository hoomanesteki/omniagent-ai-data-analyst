"""Component tests for master_node: routing via deterministic catalog match.

Catalog.match's own matching logic is covered exhaustively in
tests/unit/test_catalog.py — these tests check the node's *routing*
behavior (Command.goto and the state update), not the matching algorithm.
"""

import asyncio

import pytest
from langgraph.graph import END

from omniagent.agents.master import make_master_node
from omniagent.kernel.catalog import Catalog, DimensionInfo, MetricInfo
from omniagent.kernel.state import OmniState


@pytest.fixture
def catalog():
    return Catalog(
        dataset_id="ecommerce",
        metrics={
            "net_revenue": MetricInfo(name="net_revenue", label="Net revenue"),
            "gross_revenue": MetricInfo(
                name="gross_revenue", label="Gross revenue", synonyms=("revenue",)
            ),
        },
        dimensions={
            "orders.channel": DimensionInfo(
                name="orders.channel", label="Channel", type="categorical"
            ),
        },
    )


def _state(question: str) -> OmniState:
    return OmniState(thread_id="t1", messages=[{"role": "user", "content": question}])


class TestMasterNodeDeterministicMatch:
    def test_routes_to_semantic_agent_on_match(self, catalog):
        node = make_master_node(catalog)
        cmd = asyncio.run(node(_state("net revenue")))

        assert cmd.goto == "semantic_agent"
        assert cmd.update["matched_metric"] == "net_revenue"
        assert cmd.update["route"] == "semantic_agent"
        assert cmd.update["metric_match_score"] == 1.0
        assert cmd.update["intent"] == "metric"

    def test_routes_via_group_by_channel_question(self, catalog):
        node = make_master_node(catalog)
        cmd = asyncio.run(node(_state("net revenue by channel")))

        assert cmd.goto == "semantic_agent"
        assert cmd.update["matched_metric"] == "net_revenue"


class TestMasterNodeNoMatch:
    def test_no_match_ends_with_clarification_listing_metrics(self, catalog):
        node = make_master_node(catalog)
        cmd = asyncio.run(node(_state("what's the weather today")))

        assert cmd.goto == END
        assert cmd.update["needs_human"] is True
        assert cmd.update["route"] == "clarify"
        assert set(cmd.update["clarification"]["options"]) == {"net_revenue", "gross_revenue"}

    def test_empty_question_ends_with_clarification(self, catalog):
        node = make_master_node(catalog)
        cmd = asyncio.run(node(_state("")))

        assert cmd.goto == END
        assert cmd.update["needs_human"] is True


class TestMasterNodeAmbiguous:
    def test_ambiguous_match_ends_with_options(self):
        tied_catalog = Catalog(
            dataset_id="test",
            metrics={
                "metric_a": MetricInfo(name="metric_a", label="Widget count"),
                "metric_b": MetricInfo(name="metric_b", label="Widget count"),
            },
        )
        node = make_master_node(tied_catalog)
        cmd = asyncio.run(node(_state("widget count")))

        assert cmd.goto == END
        assert cmd.update["needs_human"] is True
        assert set(cmd.update["clarification"]["options"]) == {"metric_a", "metric_b"}
        assert cmd.update["clarification"]["question"] == "Which metric did you mean?"
