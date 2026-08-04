"""Integration tests: the full governed graph, real DuckDB, ScriptedLLM.

The critical-path acceptance criterion from the roadmap: "net revenue last
quarter" on e-commerce matches gold SQL under normalized comparison, makes
exactly one scripted-LLM call, and the response carries executed_sql.
"""

from datetime import datetime

import pytest

from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
from omniagent.agents.graph import build_governed_graph
from omniagent.kernel.gates import (
    GuardrailPolicy,
    empty_result_gate,
    llm_budget_gate,
    numeric_recompute_gate,
    pii_mask_gate,
    provenance_gate,
    row_cap_gate,
    sql_allowlist_gate,
    timeout_gate,
)
from omniagent.kernel.models import SemanticExtraction
from omniagent.kernel.state import OmniState
from omniagent.kernel.time_resolver import DefaultTimeResolver
from tests.fakes.llm import ScriptedLLM

NOW = datetime(2026, 8, 3)

ALL_GATES = [
    sql_allowlist_gate,
    row_cap_gate,
    timeout_gate,
    empty_result_gate,
    numeric_recompute_gate,
    pii_mask_gate,
    provenance_gate,
    llm_budget_gate,
]


@pytest.fixture
def provider():
    return NativeYamlProvider("packs")


def _build_graph(provider, engine, script):
    catalog = provider.catalog("ecommerce")
    llm = ScriptedLLM(script)
    graph = build_governed_graph(
        dataset_id="ecommerce",
        catalog=catalog,
        semantic_provider=provider,
        engine=engine,
        llm=llm,
        model_id="test-model",
        time_resolver=DefaultTimeResolver(),
        guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
        now_fn=lambda: NOW,
    )
    return graph, llm


class TestGovernedPathAcceptance:
    """The roadmap's literal Phase 3 'Done When' criterion."""

    @pytest.mark.integration
    async def test_net_revenue_last_quarter_end_to_end(self, provider, ecommerce_warehouse):
        graph, llm = _build_graph(
            provider,
            ecommerce_warehouse,
            [SemanticExtraction(time_phrase="last quarter", filters=[])],
        )
        initial = OmniState(
            thread_id="t1",
            dataset_id="ecommerce",
            messages=[{"role": "user", "content": "net revenue last quarter"}],
        )

        result = await graph.ainvoke(initial)

        llm.assert_call_count(1)
        assert result["executed_sql"] is not None
        assert result.get("error") is None
        # Q2 2026 (Apr 1 - Jul 1): completed orders O1 (Apr 15, 100), O2
        # (May 10, 50), O4 (Apr 5, 75) => gross_revenue = 225. R1 (on O1,
        # approved, 20) is the only approved refund on an order in range
        # (R2 on O2 is pending, excluded) => refunds = 20.
        # net_revenue = 225 - 20 = 205.
        assert result["result_set"] == [{"net_revenue": 205.0}]
        assert result["narration"] == "Net revenue was $205.00."
        assert result["chart_spec"] is None  # single KPI, no chart
        # 1.0 catalog match score minus the row_cap_gate's always-present
        # "result capped at N rows" transparency notice (one assumption).
        assert result["confidence"] == 0.9

    @pytest.mark.integration
    async def test_governed_path_never_touches_sql_fallback(self, provider, ecommerce_warehouse):
        """No sql_agent exists yet in this graph (Phase 5) — this test
        documents that the governed path is fully self-contained and
        reaches a real answer without any fallback node."""
        graph, llm = _build_graph(
            provider, ecommerce_warehouse, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        initial = OmniState(
            thread_id="t1",
            dataset_id="ecommerce",
            messages=[{"role": "user", "content": "order count"}],
        )

        result = await graph.ainvoke(initial)

        assert result["route"] == "semantic_agent"
        assert result["matched_metric"] == "order_count"
        assert result["result_set"] == [{"order_count": 3}]

    @pytest.mark.integration
    async def test_breakdown_question_produces_chart(self, provider, ecommerce_warehouse):
        graph, llm = _build_graph(
            provider, ecommerce_warehouse, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        initial = OmniState(
            thread_id="t1",
            dataset_id="ecommerce",
            messages=[{"role": "user", "content": "gross revenue by channel"}],
        )

        result = await graph.ainvoke(initial)

        llm.assert_call_count(1)
        assert result["chart_spec"] is not None
        assert result["chart_spec"]["mark"] == "bar"
        assert "web" in result["narration"]


class TestGovernedPathClarification:
    @pytest.mark.integration
    async def test_unmatched_question_ends_in_clarification_zero_llm_calls(
        self, provider, ecommerce_warehouse
    ):
        graph, llm = _build_graph(provider, ecommerce_warehouse, [])
        initial = OmniState(
            thread_id="t1",
            dataset_id="ecommerce",
            messages=[{"role": "user", "content": "what's the weather"}],
        )

        result = await graph.ainvoke(initial)

        assert result["needs_human"] is True
        assert result["clarification"] is not None
        assert result.get("executed_sql") is None
        llm.assert_call_count(0)
