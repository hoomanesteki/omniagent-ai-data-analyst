"""Component tests for master_node: routing via deterministic catalog match.

Catalog.match's own matching logic is covered exhaustively in
tests/unit/test_catalog.py — these tests check the node's *routing*
behavior (Command.goto and the state update), not the matching algorithm.
"""

import asyncio

import pytest
from langgraph.graph import END

from omniagent.agents.master import dispatch_match, make_master_node
from omniagent.kernel.catalog import Ambiguous, Catalog, DimensionInfo, Match, MetricInfo
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
        assert set(cmd.update["clarification"]["options"]) == {"Net revenue", "Gross revenue"}

    def test_empty_question_ends_with_clarification(self, catalog):
        node = make_master_node(catalog)
        cmd = asyncio.run(node(_state("")))

        assert cmd.goto == END
        assert cmd.update["needs_human"] is True


class TestMasterNodeAmbiguous:
    def test_ambiguous_match_ends_with_options(self):
        """Two distinct metrics whose synonyms tie on phrase length for the
        same question — a realistic ambiguity, unlike two metrics sharing an
        identical label (which the real packs never do, and which no amount
        of clarification text could actually disambiguate anyway)."""
        tied_catalog = Catalog(
            dataset_id="test",
            metrics={
                "metric_a": MetricInfo(
                    name="metric_a", label="Order count", synonyms=("order total",)
                ),
                "metric_b": MetricInfo(
                    name="metric_b", label="Order value", synonyms=("order total",)
                ),
            },
        )
        node = make_master_node(tied_catalog)
        cmd = asyncio.run(node(_state("order total")))

        assert cmd.goto == END
        assert cmd.update["needs_human"] is True
        assert set(cmd.update["clarification"]["options"]) == {"Order count", "Order value"}
        assert cmd.update["clarification"]["question"] == "Which metric did you mean?"

    def test_ambiguous_match_routes_to_clarify_route_when_configured(self):
        """With a clarify_route configured (a real interrupt()-based node),
        an ambiguous match pauses there instead of ending the turn -- no
        `needs_human`/`route` bookkeeping needed since the caller never has
        to start a fresh turn to answer."""
        tied_catalog = Catalog(
            dataset_id="test",
            metrics={
                "metric_a": MetricInfo(
                    name="metric_a", label="Order count", synonyms=("order total",)
                ),
                "metric_b": MetricInfo(
                    name="metric_b", label="Order value", synonyms=("order total",)
                ),
            },
        )
        node = make_master_node(tied_catalog, clarify_route="clarify")
        cmd = asyncio.run(node(_state("order total")))

        assert cmd.goto == "clarify"
        assert "needs_human" not in cmd.update
        assert set(cmd.update["clarification"]["options"]) == {"Order count", "Order value"}


class TestDispatchMatch:
    """Direct unit tests for the shared helper master_node and clarify_node
    both call, covering the routing combinations not already exercised via
    make_master_node above."""

    def test_match_clears_any_prior_clarification(self):
        cmd = dispatch_match(
            Match(metric="net_revenue", score=1.0, matched_on="name"),
            Catalog(
                dataset_id="d",
                metrics={"net_revenue": MetricInfo(name="net_revenue", label="Net revenue")},
            ),
        )
        assert cmd.update["clarification"] is None

    def test_no_match_with_fallback_route_carries_no_clarification(self):
        cmd = dispatch_match(None, Catalog(dataset_id="d"), fallback_route="fast_path")

        assert cmd.goto == "fast_path"
        assert cmd.update == {"route": "fast_path", "intent": "sql", "clarification": None}

    def test_ambiguous_without_clarify_route_ends_with_plain_dict(self):
        catalog = Catalog(
            dataset_id="d",
            metrics={
                "a": MetricInfo(name="a", label="A"),
                "b": MetricInfo(name="b", label="B"),
            },
        )
        cmd = dispatch_match(Ambiguous(candidates=("a", "b"), reason="tie"), catalog)

        assert cmd.goto == END
        assert cmd.update["needs_human"] is True
        assert cmd.update["route"] == "clarify"
