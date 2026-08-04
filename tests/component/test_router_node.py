"""Component tests for router_node: the one-call intent decision behind a
deterministic catalog miss.

Uses ScriptedLLM so the model's decision is exact and deterministic.
"""

import asyncio

from langgraph.graph import END

from omniagent.agents.router import make_router_node
from omniagent.kernel.catalog import Catalog, MetricInfo
from omniagent.kernel.models import Route
from omniagent.kernel.state import OmniState
from tests.fakes.llm import ScriptedLLM


def _catalog() -> Catalog:
    return Catalog(
        dataset_id="ecommerce",
        metrics={"net_revenue": MetricInfo(name="net_revenue", label="Net revenue")},
    )


def _state(question: str) -> OmniState:
    return OmniState(thread_id="t1", messages=[{"role": "user", "content": question}])


class TestRouterNodeIntentDecision:
    def test_sql_intent_routes_to_sql_route(self):
        llm = ScriptedLLM([Route(intent="sql", target="sql_agent", confidence=0.8)])
        node = make_router_node(catalog=_catalog(), llm=llm, model_id="m", sql_route="fast_path")

        cmd = asyncio.run(node(_state("which shipping carrier is fastest")))

        assert cmd.goto == "fast_path"
        assert cmd.update["intent"] == "sql"
        llm.assert_call_count(1)

    def test_chat_intent_ends_with_narration(self):
        llm = ScriptedLLM(
            [
                Route(
                    intent="chat",
                    target="none",
                    confidence=0.9,
                    rationale="This dataset only covers e-commerce metrics.",
                )
            ]
        )
        node = make_router_node(catalog=_catalog(), llm=llm, model_id="m")

        cmd = asyncio.run(node(_state("hello there")))

        assert cmd.goto == END
        assert cmd.update["narration"] == "This dataset only covers e-commerce metrics."

    def test_chat_intent_with_no_rationale_uses_default_narration(self):
        llm = ScriptedLLM([Route(intent="chat", target="none", confidence=0.9)])
        node = make_router_node(catalog=_catalog(), llm=llm, model_id="m")

        cmd = asyncio.run(node(_state("tell me a joke")))

        assert cmd.goto == END
        assert "dataset's metrics" in cmd.update["narration"]

    def test_needs_clarification_routes_to_clarify_route(self):
        llm = ScriptedLLM(
            [
                Route(
                    intent="chat",
                    target="none",
                    confidence=0.3,
                    needs_clarification=True,
                    rationale="Do you mean total sales or order count?",
                    clarification_options=["Total sales", "Order count"],
                )
            ]
        )
        node = make_router_node(catalog=_catalog(), llm=llm, model_id="m", clarify_route="clarify")

        cmd = asyncio.run(node(_state("how are we doing")))

        assert cmd.goto == "clarify"
        assert cmd.update["clarification"]["options"] == ["Total sales", "Order count"]
        assert cmd.update["clarification"]["question"] == "Do you mean total sales or order count?"

    def test_llm_call_and_model_calls_by_node_are_tracked(self):
        llm = ScriptedLLM([Route(intent="chat", target="none", confidence=0.9)])
        node = make_router_node(catalog=_catalog(), llm=llm, model_id="m")

        cmd = asyncio.run(node(_state("hi")))

        assert cmd.update["llm_calls"] == 1
        assert cmd.update["model_calls_by_node"]["router"] == 1
