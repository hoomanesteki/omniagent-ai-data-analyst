"""Component tests for semantic_agent_node: exactly one LLM call, deterministic
time resolution, dimension/filter validation against the real ecommerce pack.
"""

import asyncio
from datetime import datetime

import pytest
from langgraph.graph import END

from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
from omniagent.agents.query_codec import query_from_dict
from omniagent.agents.semantic_agent import make_semantic_agent_node
from omniagent.kernel.models import FilterExtraction, SemanticExtraction
from omniagent.kernel.ports.time import CalendarSpec
from omniagent.kernel.state import OmniState
from omniagent.kernel.time_resolver import DefaultTimeResolver
from tests.fakes.llm import ScriptedLLM

NOW = datetime(2026, 8, 3)


@pytest.fixture
def provider():
    return NativeYamlProvider("packs")


@pytest.fixture
def catalog(provider):
    return provider.catalog("ecommerce")


def _make_node(catalog, provider, script, *, max_calls=16):
    llm = ScriptedLLM(script, max_calls=max_calls)
    node = make_semantic_agent_node(
        dataset_id="ecommerce",
        catalog=catalog,
        semantic_provider=provider,
        llm=llm,
        model_id="test-model",
        time_resolver=DefaultTimeResolver(),
        calendar=CalendarSpec(),
        now_fn=lambda: NOW,
    )
    return node, llm


def _state(question: str, metric: str) -> OmniState:
    return OmniState(
        thread_id="t1",
        messages=[{"role": "user", "content": question}],
        matched_metric=metric,
    )


class TestSemanticAgentHappyPath:
    def test_extracts_time_phrase_and_resolves_deterministically(self, catalog, provider):
        node, llm = _make_node(
            catalog, provider, [SemanticExtraction(time_phrase="last quarter", filters=[])]
        )
        cmd = asyncio.run(node(_state("net revenue last quarter", "net_revenue")))

        assert cmd.goto == "executor"
        llm.assert_call_count(1)
        query = query_from_dict(cmd.update["semantic_query"])
        assert query.metrics == ("net_revenue",)
        assert query.time_range is not None
        assert query.time_range.start.isoformat() == "2026-04-01"
        assert query.time_range.end.isoformat() == "2026-07-01"

    def test_no_time_phrase_leaves_time_range_none(self, catalog, provider):
        node, llm = _make_node(
            catalog, provider, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        cmd = asyncio.run(node(_state("net revenue", "net_revenue")))

        query = query_from_dict(cmd.update["semantic_query"])
        assert query.time_range is None
        llm.assert_call_count(1)

    def test_group_by_dimension_matched_deterministically_not_via_llm(self, catalog, provider):
        node, llm = _make_node(
            catalog, provider, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        cmd = asyncio.run(node(_state("net revenue by channel", "net_revenue")))

        query = query_from_dict(cmd.update["semantic_query"])
        assert "orders.channel" in query.group_by
        llm.assert_call_count(1)

    def test_valid_filter_extraction_applied(self, catalog, provider):
        extraction = SemanticExtraction(
            time_phrase=None,
            filters=[FilterExtraction(dimension="orders.channel", value="web")],
        )
        node, llm = _make_node(catalog, provider, [extraction])
        cmd = asyncio.run(node(_state("net revenue on web", "net_revenue")))

        query = query_from_dict(cmd.update["semantic_query"])
        assert len(query.filters) == 1
        assert query.filters[0].field == "orders.channel"
        assert query.filters[0].value == "web"

    def test_llm_calls_and_model_calls_by_node_incremented(self, catalog, provider):
        node, llm = _make_node(
            catalog, provider, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        state = _state("net revenue", "net_revenue")
        cmd = asyncio.run(node(state))

        assert cmd.update["llm_calls"] == state.llm_calls + 1
        assert cmd.update["model_calls_by_node"]["semantic_agent"] == 1


class TestSemanticAgentEdgeCases:
    def test_unrecognized_time_phrase_recorded_as_assumption_not_fatal(self, catalog, provider):
        extraction = SemanticExtraction(time_phrase="sometime last tuesday-ish", filters=[])
        node, llm = _make_node(catalog, provider, [extraction])
        cmd = asyncio.run(node(_state("net revenue", "net_revenue")))

        assert cmd.goto == "executor"
        query = query_from_dict(cmd.update["semantic_query"])
        assert query.time_range is None
        assert any("Could not interpret" in a for a in cmd.update["assumptions"])

    def test_filter_on_unrecognized_dimension_dropped_with_assumption(self, catalog, provider):
        extraction = SemanticExtraction(
            time_phrase=None,
            filters=[FilterExtraction(dimension="not_a_real_dimension", value="x")],
        )
        node, llm = _make_node(catalog, provider, [extraction])
        cmd = asyncio.run(node(_state("net revenue", "net_revenue")))

        query = query_from_dict(cmd.update["semantic_query"])
        assert query.filters == ()
        assert any("Ignored filter" in a for a in cmd.update["assumptions"])

    def test_no_matched_metric_is_a_wiring_error_not_a_crash(self, catalog, provider):
        node, llm = _make_node(
            catalog, provider, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        state = OmniState(
            thread_id="t1", messages=[{"role": "user", "content": "net revenue"}]
        )  # matched_metric never set

        cmd = asyncio.run(node(state))

        assert cmd.goto == END
        assert "error" in cmd.update
        llm.assert_call_count(0)

    def test_fan_out_validation_failure_ends_with_error_not_exception(self, catalog, provider):
        """customer_count (customers-grain) grouped by orders.channel
        (orders-grain) would fan out the customer count across each
        customer's orders — the deterministic dimension match ("channel"
        appears in the question) plus the customer_count metric together
        produce an invalid query, and that must surface as a clean
        terminal error rather than an uncaught SemanticIssue."""
        node, llm = _make_node(
            catalog, provider, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        cmd = asyncio.run(node(_state("customers by channel", "customer_count")))

        assert cmd.goto == END
        assert "error" in cmd.update
        assert "fan" in cmd.update["error"].lower() or "multiply" in cmd.update["error"].lower()
        llm.assert_call_count(1)
