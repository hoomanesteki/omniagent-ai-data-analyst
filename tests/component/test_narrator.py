"""Component tests for narrator: template narration, deterministic
confidence, and the critic-trigger decision — against the real ecommerce
pack so number formatting reflects an actual declared DisplayFormat."""

import asyncio

import pytest
from langgraph.graph import END

from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
from omniagent.agents.narrator import (
    CRITIC_CONFIDENCE_THRESHOLD,
    compute_confidence,
    make_narrator_node,
    narrate,
    needs_critic,
)
from omniagent.agents.query_codec import query_to_dict
from omniagent.kernel.ports.semantic import SemanticQuery
from omniagent.kernel.state import OmniState


@pytest.fixture
def catalog():
    return NativeYamlProvider("packs").catalog("ecommerce")


def _state_with_result(query: SemanticQuery, result_set: list[dict], **kwargs) -> OmniState:
    return OmniState(
        thread_id="t1",
        dataset_id="ecommerce",
        semantic_query=query_to_dict(query),
        result_set=result_set,
        matched_metric=query.metrics[0] if query.metrics else None,
        **kwargs,
    )


class TestNarrateSingleKPI:
    def test_formats_using_metric_declared_currency(self, catalog):
        state = _state_with_result(
            SemanticQuery(metrics=("gross_revenue",), limit=10), [{"gross_revenue": 225.0}]
        )
        narration, chart = narrate(state, catalog)

        assert narration == "Gross revenue was $225.00."
        assert chart is None

    def test_number_type_metric_no_currency(self, catalog):
        state = _state_with_result(
            SemanticQuery(metrics=("order_count",), limit=10), [{"order_count": 3}]
        )
        narration, chart = narrate(state, catalog)

        assert "3" in narration
        assert "$" not in narration


class TestNarrateBreakdown:
    def test_leads_with_top_group_by_metric_value(self, catalog):
        state = _state_with_result(
            SemanticQuery(metrics=("gross_revenue",), group_by=("orders.channel",), limit=10),
            [
                {"orders__channel": "web", "gross_revenue": 150.0},
                {"orders__channel": "mobile_app", "gross_revenue": 75.0},
            ],
        )
        narration, chart = narrate(state, catalog)

        assert "web" in narration
        assert "$150.00" in narration
        assert chart is not None
        assert chart.mark == "bar"

    def test_single_group_no_more_groups_phrasing(self, catalog):
        state = _state_with_result(
            SemanticQuery(metrics=("gross_revenue",), group_by=("orders.channel",), limit=10),
            [{"orders__channel": "web", "gross_revenue": 150.0}],
        )
        narration, _ = narrate(state, catalog)

        assert narration == "Gross revenue for web was $150.00."


class TestNarrateEdgeCases:
    def test_no_semantic_query_returns_no_results(self, catalog):
        state = OmniState(thread_id="t1", dataset_id="ecommerce")
        narration, chart = narrate(state, catalog)

        assert narration == "No results."
        assert chart is None

    def test_empty_result_set_returns_no_results(self, catalog):
        state = _state_with_result(SemanticQuery(metrics=("gross_revenue",), limit=10), [])
        narration, chart = narrate(state, catalog)

        assert narration == "No results."


class TestComputeConfidence:
    def test_full_match_score_no_assumptions_full_confidence(self):
        state = OmniState(thread_id="t1", metric_match_score=1.0)
        assert compute_confidence(state) == 1.0

    def test_assumptions_reduce_confidence(self):
        state = OmniState(thread_id="t1", metric_match_score=1.0, assumptions=["dropped a filter"])
        assert compute_confidence(state) == pytest.approx(0.9)

    def test_multiple_assumptions_compound(self):
        state = OmniState(thread_id="t1", metric_match_score=1.0, assumptions=["a", "b", "c"])
        assert compute_confidence(state) == pytest.approx(0.7)

    def test_truncated_result_reduces_confidence(self):
        state = OmniState(thread_id="t1", metric_match_score=1.0, result_meta={"truncated": True})
        assert compute_confidence(state) == pytest.approx(0.9)

    def test_confidence_never_negative(self):
        state = OmniState(
            thread_id="t1",
            metric_match_score=0.5,
            assumptions=["a", "b", "c", "d", "e", "f"],
        )
        assert compute_confidence(state) == 0.0


class TestNeedsCritic:
    def test_low_confidence_needs_critic(self):
        state = OmniState(thread_id="t1")
        assert needs_critic(state, CRITIC_CONFIDENCE_THRESHOLD - 0.01) is True

    def test_high_confidence_no_assumptions_skips_critic(self):
        state = OmniState(thread_id="t1", assumptions=[])
        assert needs_critic(state, 1.0) is False

    def test_high_confidence_with_assumptions_still_needs_critic(self):
        state = OmniState(thread_id="t1", assumptions=["dropped a filter"])
        assert needs_critic(state, 1.0) is True


class TestNarratorNode:
    def test_node_populates_narration_chart_confidence(self, catalog):
        node = make_narrator_node(catalog)
        state = _state_with_result(
            SemanticQuery(metrics=("gross_revenue",), limit=10),
            [{"gross_revenue": 225.0}],
            metric_match_score=1.0,
        )

        cmd = asyncio.run(node(state))

        assert cmd.goto == END
        assert cmd.update["narration"] == "Gross revenue was $225.00."
        assert cmd.update["chart_spec"] is None
        assert cmd.update["confidence"] == 1.0

    def test_node_skips_narration_when_upstream_error_present(self, catalog):
        node = make_narrator_node(catalog)
        state = OmniState(thread_id="t1", dataset_id="ecommerce", error="something failed")

        cmd = asyncio.run(node(state))

        assert cmd.goto == END
        assert "narration" not in cmd.update

    def test_node_serializes_chart_spec_to_dict(self, catalog):
        node = make_narrator_node(catalog)
        state = _state_with_result(
            SemanticQuery(metrics=("gross_revenue",), group_by=("orders.channel",), limit=10),
            [
                {"orders__channel": "web", "gross_revenue": 150.0},
                {"orders__channel": "mobile_app", "gross_revenue": 75.0},
            ],
        )

        cmd = asyncio.run(node(state))

        assert isinstance(cmd.update["chart_spec"], dict)
        assert cmd.update["chart_spec"]["mark"] == "bar"
