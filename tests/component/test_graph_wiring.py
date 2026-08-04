"""Component tests for build_governed_graph's node wiring.

These check which nodes exist under each configuration combination without
ever running the graph -- no real engine, LLM, or checkpointer needed for
that, since `interrupt()`, gate execution, and model calls only matter once
a run actually happens (covered by tests/integration instead). A wiring
mistake here (the wrong node attached, or attached when it shouldn't be) is
exactly the class of bug this catches cheaply, before ever reaching a real
run.
"""

from langgraph.checkpoint.memory import InMemorySaver

from omniagent.agents.graph import build_governed_graph
from omniagent.kernel.catalog import Catalog, MetricInfo
from omniagent.kernel.gates import GuardrailPolicy
from omniagent.kernel.ports.semantic import SemanticCapabilities
from omniagent.kernel.time_resolver import DefaultTimeResolver
from tests.fakes.llm import ScriptedLLM


class _FakeSemanticProvider:
    def capabilities(self) -> SemanticCapabilities:
        return SemanticCapabilities(
            ratio=False,
            derived=False,
            cumulative=False,
            conversion=False,
            percentiles=False,
            semi_additive=False,
            custom_calendar=False,
        )

    def catalog(self, dataset_id):
        raise NotImplementedError

    def schema_version(self, dataset_id: str) -> str:
        return "v1"

    def validate(self, dataset_id, query):
        return []

    def compile(self, dataset_id, query):
        raise NotImplementedError


def _catalog() -> Catalog:
    return Catalog(
        dataset_id="d", metrics={"net_revenue": MetricInfo(name="net_revenue", label="Net revenue")}
    )


def _build(**overrides):
    defaults = {
        "dataset_id": "d",
        "catalog": _catalog(),
        "semantic_provider": _FakeSemanticProvider(),
        "engine": None,
        "llm": ScriptedLLM([]),
        "model_id": "m",
        "time_resolver": DefaultTimeResolver(),
        "guardrail_policy": GuardrailPolicy(gates=[]),
    }
    defaults.update(overrides)
    return build_governed_graph(**defaults)


def _node_names(graph) -> set[str]:
    return set(graph.get_graph().nodes.keys())


class TestCoreWiring:
    def test_bare_graph_has_only_the_governed_path_nodes(self):
        nodes = _node_names(_build())

        assert {"master", "semantic_agent", "executor", "narrator"} <= nodes
        assert "fast_path" not in nodes
        assert "sql_agent" not in nodes
        assert "clarify" not in nodes
        assert "router" not in nodes


class TestSqlFallbackWiring:
    def test_verified_query_store_attaches_fast_path_and_sql_agent(self):
        nodes = _node_names(_build(verified_query_store=object()))

        assert "fast_path" in nodes
        assert "sql_agent" in nodes
        assert "clarify" not in nodes
        assert "router" not in nodes


class TestCheckpointerWiring:
    def test_checkpointer_alone_attaches_clarify_but_not_router(self):
        nodes = _node_names(_build(checkpointer=InMemorySaver()))

        assert "clarify" in nodes
        assert "router" not in nodes
        assert "fast_path" not in nodes

    def test_checkpointer_and_fallback_together_still_omit_router_without_use_router(self):
        nodes = _node_names(_build(checkpointer=InMemorySaver(), verified_query_store=object()))

        assert "clarify" in nodes
        assert "fast_path" in nodes
        assert "router" not in nodes


class TestRouterWiring:
    def test_use_router_alone_does_not_attach_router(self):
        """use_router without both a checkpointer and a verified_query_store
        has nowhere safe to send its clarify/sql branches, so it silently
        does not attach -- degrading to whatever the other flags already
        wired, not a caller error."""
        nodes = _node_names(_build(use_router=True))

        assert "router" not in nodes

    def test_use_router_needs_both_checkpointer_and_fallback(self):
        nodes = _node_names(
            _build(use_router=True, checkpointer=InMemorySaver(), verified_query_store=object())
        )

        assert "router" in nodes
        assert "clarify" in nodes
        assert "fast_path" in nodes

    def test_use_router_with_only_checkpointer_does_not_attach(self):
        nodes = _node_names(_build(use_router=True, checkpointer=InMemorySaver()))

        assert "router" not in nodes

    def test_use_router_with_only_fallback_does_not_attach(self):
        nodes = _node_names(_build(use_router=True, verified_query_store=object()))

        assert "router" not in nodes
