"""Integration tests for the MCP server: real graph, real DuckDB warehouse
fixture, ScriptedLLM, real checkpointer -- every tool exercised through
`MCPServer.call_tool`, the same entry point a real MCP client goes through.

Mirrors tests/integration/test_service.py's fixture shape deliberately:
the whole point of this channel is that it drives the exact same
DatasetRuntime/graph/gate-stack machinery, so its test suite should prove
the same behaviors through a different transport, not a different set of
behaviors.
"""

from datetime import datetime

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from mcp.server.mcpserver.exceptions import ToolError

from omniagent.adapters.embeddings import FastEmbedProvider
from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
from omniagent.adapters.vectors import DuckDBVSSStore
from omniagent.agents.graph import build_governed_graph
from omniagent.channels.mcp_server import build_mcp_server
from omniagent.channels.service import DatasetRuntime
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
from omniagent.kernel.models import Route, SemanticExtraction, SqlCandidate
from omniagent.kernel.time_resolver import DefaultTimeResolver
from omniagent.memory.verified_queries import DuckDBVerifiedQueryStore
from tests.fakes.llm import ScriptedLLM

# See tests/contract/test_verified_queries.py's pytestmark comment: shared xdist_group so
# concurrent workers don't race to load the real embedding model at once.
pytestmark = pytest.mark.xdist_group(name="fastembed")

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


@pytest.fixture(scope="module")
def embedder():
    return FastEmbedProvider()


def _server(
    provider,
    engine,
    script,
    *,
    verified_query_store=None,
    use_router=False,
):
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
        verified_query_store=verified_query_store,
        checkpointer=InMemorySaver(),
        use_router=use_router,
    )
    runtime = DatasetRuntime(
        dataset_id="ecommerce",
        label="E-commerce",
        description="Test dataset",
        catalog=catalog,
        graph=graph,
        schema_version=provider.schema_version("ecommerce"),
        verified_query_store=verified_query_store,
    )
    return build_mcp_server({"ecommerce": runtime}), llm


@pytest.mark.integration
class TestListDatasets:
    async def test_lists_ecommerce_with_starters(self, provider, ecommerce_warehouse):
        server, _ = _server(provider, ecommerce_warehouse, [])
        result = await server.call_tool("list_datasets", {})
        body = result.structured_content["result"]
        assert len(body) == 1
        assert body[0]["dataset_id"] == "ecommerce"
        assert len(body[0]["starter_questions"]) > 0


@pytest.mark.integration
class TestNoRawSqlTool:
    async def test_only_the_four_governed_tools_are_exposed(self, provider, ecommerce_warehouse):
        """The whole safety point of this channel: an MCP client gets
        discovery/ask/resume/feedback and nothing that lets it hand the
        engine arbitrary SQL directly."""
        server, _ = _server(provider, ecommerce_warehouse, [])
        tools = await server.list_tools()
        assert {t.name for t in tools} == {"list_datasets", "ask", "resume", "feedback"}


@pytest.mark.integration
class TestAsk:
    async def test_ask_returns_answer_envelope_with_thread_id(self, provider, ecommerce_warehouse):
        server, llm = _server(
            provider, ecommerce_warehouse, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        result = await server.call_tool(
            "ask", {"dataset_id": "ecommerce", "question": "gross revenue"}
        )
        body = result.structured_content
        assert body["kind"] == "answer"
        assert body["narration"] == "Gross revenue was $225.00."
        assert body["thread_id"]
        assert body["executed_sql"] is not None
        llm.assert_call_count(1)

    async def test_ask_unknown_dataset_raises(self, provider, ecommerce_warehouse):
        server, _ = _server(provider, ecommerce_warehouse, [])
        with pytest.raises(ToolError, match="Unknown dataset"):
            await server.call_tool("ask", {"dataset_id": "nope", "question": "x"})

    async def test_ask_unmatched_question_returns_clarification(
        self, provider, ecommerce_warehouse
    ):
        server, llm = _server(provider, ecommerce_warehouse, [])
        result = await server.call_tool(
            "ask", {"dataset_id": "ecommerce", "question": "what's the weather"}
        )
        body = result.structured_content
        assert body["kind"] == "clarification"
        assert body["resumable"] is False
        assert body["clarification"]["options"]
        llm.assert_call_count(0)

    async def test_ask_reuses_thread_id_when_provided(self, provider, ecommerce_warehouse):
        server, llm = _server(
            provider,
            ecommerce_warehouse,
            [
                SemanticExtraction(time_phrase=None, filters=[]),
                SemanticExtraction(time_phrase=None, filters=[]),
            ],
        )
        first = (
            await server.call_tool("ask", {"dataset_id": "ecommerce", "question": "order count"})
        ).structured_content
        second = (
            await server.call_tool(
                "ask",
                {
                    "dataset_id": "ecommerce",
                    "question": "gross revenue",
                    "thread_id": first["thread_id"],
                },
            )
        ).structured_content

        assert second["thread_id"] == first["thread_id"]
        assert second["narration"] == "Gross revenue was $225.00."


@pytest.mark.integration
class TestResume:
    async def test_resume_on_a_completed_thread_raises(self, provider, ecommerce_warehouse):
        server, llm = _server(
            provider, ecommerce_warehouse, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        ask_body = (
            await server.call_tool("ask", {"dataset_id": "ecommerce", "question": "order count"})
        ).structured_content
        assert ask_body["kind"] == "answer"

        with pytest.raises(ToolError, match="no pending clarification"):
            await server.call_tool(
                "resume", {"thread_id": ask_body["thread_id"], "message": "anything"}
            )

    async def test_resume_unknown_thread_raises(self, provider, ecommerce_warehouse):
        server, _ = _server(provider, ecommerce_warehouse, [])
        with pytest.raises(ToolError, match="Unknown thread"):
            await server.call_tool("resume", {"thread_id": "nonexistent", "message": "x"})

    async def test_router_clarification_pauses_then_resume_answers_it(
        self, provider, ecommerce_warehouse, embedder
    ):
        with DuckDBVSSStore(dim=embedder.dim) as vstore:
            verified_query_store = DuckDBVerifiedQueryStore(vstore, embedder)
            server, llm = _server(
                provider,
                ecommerce_warehouse,
                [
                    Route(
                        intent="chat",
                        target="none",
                        confidence=0.3,
                        needs_clarification=True,
                        rationale="Do you mean order count or gross revenue?",
                        clarification_options=["Order count", "Gross revenue"],
                    ),
                    SemanticExtraction(time_phrase=None, filters=[]),
                ],
                verified_query_store=verified_query_store,
                use_router=True,
            )

            ask_body = (
                await server.call_tool(
                    "ask", {"dataset_id": "ecommerce", "question": "how are we doing"}
                )
            ).structured_content
            assert ask_body["kind"] == "clarification"
            assert ask_body["resumable"] is True
            assert ask_body["clarification"]["options"] == ["Order count", "Gross revenue"]

            resume_body = (
                await server.call_tool(
                    "resume",
                    {"thread_id": ask_body["thread_id"], "message": "gross revenue"},
                )
            ).structured_content
            assert resume_body["thread_id"] == ask_body["thread_id"]
            assert resume_body["narration"] == "Gross revenue was $225.00."


@pytest.mark.integration
class TestFeedback:
    async def test_feedback_records_thumbs_up(self, provider, ecommerce_warehouse):
        server, llm = _server(
            provider, ecommerce_warehouse, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        ask_body = (
            await server.call_tool("ask", {"dataset_id": "ecommerce", "question": "order count"})
        ).structured_content

        result = await server.call_tool(
            "feedback", {"thread_id": ask_body["thread_id"], "rating": "up"}
        )
        assert result.structured_content["status"] == "recorded"

    async def test_feedback_on_fallback_answer_creates_a_verified_query(
        self, provider, ecommerce_warehouse, embedder
    ):
        with DuckDBVSSStore(dim=embedder.dim) as vstore:
            verified_query_store = DuckDBVerifiedQueryStore(vstore, embedder)
            server, llm = _server(
                provider,
                ecommerce_warehouse,
                [
                    SqlCandidate(
                        sql="SELECT DISTINCT discount_code FROM ecommerce_orders WHERE discount_code IS NOT NULL",
                        tables_used=["ecommerce_orders"],
                    )
                ],
                verified_query_store=verified_query_store,
            )
            ask_body = (
                await server.call_tool(
                    "ask",
                    {
                        "dataset_id": "ecommerce",
                        "question": "list the distinct discount codes used",
                    },
                )
            ).structured_content
            assert ask_body["kind"] == "answer"

            result = await server.call_tool(
                "feedback", {"thread_id": ask_body["thread_id"], "rating": "up"}
            )
            assert result.structured_content["verified_query_created"] is True

    async def test_feedback_unknown_thread_raises(self, provider, ecommerce_warehouse):
        server, _ = _server(provider, ecommerce_warehouse, [])
        with pytest.raises(ToolError, match="Unknown thread"):
            await server.call_tool("feedback", {"thread_id": "nonexistent", "rating": "up"})

    async def test_feedback_invalid_rating_raises(self, provider, ecommerce_warehouse):
        server, llm = _server(
            provider, ecommerce_warehouse, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        ask_body = (
            await server.call_tool("ask", {"dataset_id": "ecommerce", "question": "order count"})
        ).structured_content

        with pytest.raises(ToolError, match="rating must be"):
            await server.call_tool(
                "feedback", {"thread_id": ask_body["thread_id"], "rating": "sideways"}
            )
