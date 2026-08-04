"""Unit tests for deterministic follow-up suggestions."""

import pytest

from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
from omniagent.agents.query_codec import query_to_dict
from omniagent.agents.suggester import suggest_followups
from omniagent.kernel.ports.semantic import SemanticQuery
from omniagent.kernel.state import OmniState


@pytest.fixture
def catalog():
    return NativeYamlProvider("packs").catalog("ecommerce")


def _state_with_query(query: SemanticQuery) -> OmniState:
    return OmniState(thread_id="t1", dataset_id="ecommerce", semantic_query=query_to_dict(query))


class TestSuggestFollowups:
    def test_no_semantic_query_returns_empty(self, catalog):
        state = OmniState(thread_id="t1", dataset_id="ecommerce")
        assert suggest_followups(state, catalog) == []

    def test_suggests_dimension_breakdown_when_none_used(self, catalog):
        state = _state_with_query(SemanticQuery(metrics=("gross_revenue",), limit=10))
        suggestions = suggest_followups(state, catalog)

        assert any("Gross revenue by" in s for s in suggestions)

    def test_never_suggests_pii_dimension(self, catalog):
        state = _state_with_query(SemanticQuery(metrics=("gross_revenue",), limit=10))
        suggestions = suggest_followups(state, catalog)

        assert not any("email" in s.lower() for s in suggestions)

    def test_does_not_resuggest_already_used_dimension(self, catalog):
        state = _state_with_query(
            SemanticQuery(metrics=("gross_revenue",), group_by=("orders.channel",), limit=10)
        )
        suggestions = suggest_followups(state, catalog)

        assert not any("by Channel" in s for s in suggestions)

    def test_suggests_other_metrics_not_yet_used(self, catalog):
        """Dimension breakdowns are capped below the total suggestion limit
        specifically so a metric suggestion always has room."""
        state = _state_with_query(SemanticQuery(metrics=("gross_revenue",), limit=10))
        suggestions = suggest_followups(state, catalog)

        assert any("by" not in s for s in suggestions)

    def test_mixes_dimension_and_metric_suggestions(self, catalog):
        state = _state_with_query(SemanticQuery(metrics=("gross_revenue",), limit=10))
        suggestions = suggest_followups(state, catalog)

        dimension_style = [s for s in suggestions if " by " in s]
        metric_style = [s for s in suggestions if " by " not in s]
        assert len(dimension_style) <= 2
        assert len(metric_style) >= 1

    def test_caps_at_max_suggestions(self, catalog):
        state = _state_with_query(SemanticQuery(metrics=("gross_revenue",), limit=10))
        suggestions = suggest_followups(state, catalog)

        assert len(suggestions) <= 3
