"""Integration tests: tracing wired into the real governed graph.

Confirms the caller-owned `tracers` dict (see graph.py's `_traced` wrapper)
actually gets populated by a real graph run, spans cover every node that
ran, inputs are genuinely masked (not just passed through), and an
interrupt()-based pause is recorded as paused rather than errored.
"""

from datetime import datetime

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
from omniagent.agents.graph import build_governed_graph
from omniagent.kernel.catalog import Catalog, MetricInfo
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
from omniagent.kernel.telemetry import Tracer
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


@pytest.mark.integration
class TestGovernedGraphTracing:
    async def test_governed_path_records_a_span_per_node_it_actually_visited(
        self, provider, ecommerce_warehouse
    ):
        catalog = provider.catalog("ecommerce")
        tracers: dict[str, Tracer] = {}
        llm = ScriptedLLM([SemanticExtraction(time_phrase=None, filters=[])])
        graph = build_governed_graph(
            dataset_id="ecommerce",
            catalog=catalog,
            semantic_provider=provider,
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="test-model",
            time_resolver=DefaultTimeResolver(),
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            now_fn=lambda: NOW,
            tracers=tracers,
        )

        await graph.ainvoke(
            OmniState(
                thread_id="trace-1",
                dataset_id="ecommerce",
                messages=[{"role": "user", "content": "gross revenue"}],
            )
        )

        span_names = [span.name for span in tracers["trace-1"].trace.spans]
        assert span_names == ["master", "semantic_agent", "executor", "narrator"]
        assert all(span.error is None for span in tracers["trace-1"].trace.spans)

    async def test_a_question_containing_pii_is_masked_in_the_recorded_span(
        self, provider, ecommerce_warehouse
    ):
        catalog = provider.catalog("ecommerce")
        tracers: dict[str, Tracer] = {}
        llm = ScriptedLLM([SemanticExtraction(time_phrase=None, filters=[])])
        graph = build_governed_graph(
            dataset_id="ecommerce",
            catalog=catalog,
            semantic_provider=provider,
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="test-model",
            time_resolver=DefaultTimeResolver(),
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            now_fn=lambda: NOW,
            tracers=tracers,
        )

        await graph.ainvoke(
            OmniState(
                thread_id="trace-2",
                dataset_id="ecommerce",
                messages=[{"role": "user", "content": "gross revenue for jane@example.com"}],
            )
        )

        master_span = tracers["trace-2"].trace.spans[0]
        recorded_content = master_span.inputs["messages"][0]["content"]
        assert "jane@example.com" not in recorded_content
        assert "***@***" in recorded_content

    async def test_no_tracers_dict_means_no_tracing_and_no_behavior_change(
        self, provider, ecommerce_warehouse
    ):
        catalog = provider.catalog("ecommerce")
        llm = ScriptedLLM([SemanticExtraction(time_phrase=None, filters=[])])
        graph = build_governed_graph(
            dataset_id="ecommerce",
            catalog=catalog,
            semantic_provider=provider,
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="test-model",
            time_resolver=DefaultTimeResolver(),
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            now_fn=lambda: NOW,
        )

        result = await graph.ainvoke(
            OmniState(
                thread_id="trace-3",
                dataset_id="ecommerce",
                messages=[{"role": "user", "content": "gross revenue"}],
            )
        )

        assert result["narration"] == "Gross revenue was $225.00."

    async def test_an_interrupt_based_pause_is_recorded_as_paused_not_errored(self, provider):
        tied_catalog = Catalog(
            dataset_id="ecommerce",
            metrics={
                "metric_a": MetricInfo(
                    name="metric_a", label="Order count", synonyms=("order total",)
                ),
                "metric_b": MetricInfo(
                    name="metric_b", label="Order value", synonyms=("order total",)
                ),
            },
        )
        tracers: dict[str, Tracer] = {}
        graph = build_governed_graph(
            dataset_id="ecommerce",
            catalog=tied_catalog,
            semantic_provider=provider,
            engine=None,
            llm=ScriptedLLM([]),
            model_id="test-model",
            time_resolver=DefaultTimeResolver(),
            guardrail_policy=GuardrailPolicy(gates=[]),
            now_fn=lambda: NOW,
            checkpointer=InMemorySaver(),
            tracers=tracers,
        )
        config = {"configurable": {"thread_id": "trace-4"}}

        await graph.ainvoke(
            OmniState(
                thread_id="trace-4",
                dataset_id="ecommerce",
                messages=[{"role": "user", "content": "order total"}],
            ),
            config,
        )

        clarify_spans = [span for span in tracers["trace-4"].trace.spans if span.name == "clarify"]
        assert len(clarify_spans) == 1
        assert clarify_spans[0].paused is True
        assert clarify_spans[0].error is None
