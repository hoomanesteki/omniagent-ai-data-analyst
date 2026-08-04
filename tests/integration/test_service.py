"""Integration tests for the FastAPI service: real graph, real DuckDB
warehouse fixture, ScriptedLLM, real checkpointer -- every endpoint
exercised through an actual HTTP-shaped TestClient request/response cycle.

Thread continuity is LangGraph's checkpointer now (see service.py), not an
app-level message store, so every test client wires one -- `InMemorySaver`
is equivalent to the real `SqliteSaver` scripts/serve.py uses for these
purposes, just without touching disk.
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from omniagent.adapters.embeddings import FastEmbedProvider
from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
from omniagent.adapters.vectors import DuckDBVSSStore
from omniagent.agents.graph import build_governed_graph
from omniagent.channels.service import DatasetRuntime, create_app
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


def _client(
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
    app = create_app({"ecommerce": runtime})
    return TestClient(app), llm


@pytest.mark.integration
class TestHealthAndDatasets:
    def test_health(self, provider, ecommerce_warehouse):
        client, _ = _client(provider, ecommerce_warehouse, [])
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_datasets_lists_ecommerce_with_starters(self, provider, ecommerce_warehouse):
        client, _ = _client(provider, ecommerce_warehouse, [])
        response = client.get("/datasets")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["dataset_id"] == "ecommerce"
        assert len(body[0]["starter_questions"]) > 0


@pytest.mark.integration
class TestAsk:
    def test_ask_returns_answer_envelope_with_thread_id(self, provider, ecommerce_warehouse):
        client, llm = _client(
            provider, ecommerce_warehouse, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        response = client.post(
            "/ask", json={"dataset_id": "ecommerce", "question": "gross revenue"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["kind"] == "answer"
        assert body["narration"] == "Gross revenue was $225.00."
        assert body["thread_id"]
        assert body["executed_sql"] is not None
        llm.assert_call_count(1)

    def test_ask_unknown_dataset_404(self, provider, ecommerce_warehouse):
        client, _ = _client(provider, ecommerce_warehouse, [])
        response = client.post("/ask", json={"dataset_id": "nope", "question": "x"})
        assert response.status_code == 404

    def test_ask_unmatched_question_returns_clarification(self, provider, ecommerce_warehouse):
        """No fallback/router configured, so a total catalog miss still ends
        with the plain (non-paused) clarification -- a checkpointer alone
        doesn't change this branch; only a fallback_route does."""
        client, llm = _client(provider, ecommerce_warehouse, [])
        response = client.post(
            "/ask", json={"dataset_id": "ecommerce", "question": "what's the weather"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["kind"] == "clarification"
        assert body["resumable"] is False
        assert body["thread_id"]
        assert body["clarification"]["options"]
        llm.assert_call_count(0)

    def test_ask_breakdown_includes_rows_and_chart(self, provider, ecommerce_warehouse):
        client, llm = _client(
            provider, ecommerce_warehouse, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        response = client.post(
            "/ask", json={"dataset_id": "ecommerce", "question": "gross revenue by channel"}
        )

        body = response.json()
        assert body["chart"]["mark"] == "bar"
        assert len(body["rows"]) == 2

    def test_ask_answer_includes_followup_suggestions(self, provider, ecommerce_warehouse):
        client, llm = _client(
            provider, ecommerce_warehouse, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        response = client.post(
            "/ask", json={"dataset_id": "ecommerce", "question": "gross revenue"}
        )

        assert response.json()["suggestions"]

    def test_ask_reuses_thread_id_when_provided(self, provider, ecommerce_warehouse):
        client, llm = _client(
            provider,
            ecommerce_warehouse,
            [
                SemanticExtraction(time_phrase=None, filters=[]),
                SemanticExtraction(time_phrase=None, filters=[]),
            ],
        )
        first = client.post(
            "/ask", json={"dataset_id": "ecommerce", "question": "order count"}
        ).json()
        second = client.post(
            "/ask",
            json={
                "dataset_id": "ecommerce",
                "question": "gross revenue",
                "thread_id": first["thread_id"],
            },
        ).json()

        assert second["thread_id"] == first["thread_id"]
        assert second["narration"] == "Gross revenue was $225.00."


@pytest.mark.integration
class TestResume:
    """`/resume` answers a pending interrupt()-based clarification -- a
    follow-up question in an already-completed conversation goes through
    `/ask` with the same thread_id instead (see TestAsk above); the
    checkpointer accumulates message history either way."""

    def test_resume_on_a_completed_thread_is_a_client_error(self, provider, ecommerce_warehouse):
        client, llm = _client(
            provider, ecommerce_warehouse, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        ask_body = client.post(
            "/ask", json={"dataset_id": "ecommerce", "question": "order count"}
        ).json()
        assert ask_body["kind"] == "answer"

        # No pending interrupt on this thread -- resuming it is a client error.
        response = client.post(
            "/resume", json={"thread_id": ask_body["thread_id"], "message": "anything"}
        )
        assert response.status_code == 409

    def test_resume_unknown_thread_404(self, provider, ecommerce_warehouse):
        client, _ = _client(provider, ecommerce_warehouse, [])
        response = client.post("/resume", json={"thread_id": "nonexistent", "message": "x"})
        assert response.status_code == 404


@pytest.mark.integration
class TestResumeWithRouter:
    """The router's needs_clarification branch is what actually produces a
    pending interrupt in this service (master's own ambiguous-match case
    needs two catalog-known metrics tied on the same phrase, which the
    shipped ecommerce pack doesn't happen to have)."""

    def test_router_clarification_pauses_then_resume_answers_it(
        self, provider, ecommerce_warehouse, embedder
    ):
        with DuckDBVSSStore(dim=embedder.dim) as vstore:
            verified_query_store = DuckDBVerifiedQueryStore(vstore, embedder)
            client, llm = _client(
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

            ask_body = client.post(
                "/ask", json={"dataset_id": "ecommerce", "question": "how are we doing"}
            ).json()
            assert ask_body["kind"] == "clarification"
            assert ask_body["resumable"] is True
            assert ask_body["clarification"]["options"] == ["Order count", "Gross revenue"]

            resume_response = client.post(
                "/resume",
                json={"thread_id": ask_body["thread_id"], "message": "gross revenue"},
            )
            assert resume_response.status_code == 200
            resume_body = resume_response.json()
            assert resume_body["thread_id"] == ask_body["thread_id"]
            assert resume_body["narration"] == "Gross revenue was $225.00."


@pytest.mark.integration
class TestFeedback:
    def test_feedback_records_thumbs_up(self, provider, ecommerce_warehouse):
        client, llm = _client(
            provider, ecommerce_warehouse, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        ask_body = client.post(
            "/ask", json={"dataset_id": "ecommerce", "question": "order count"}
        ).json()

        response = client.post(
            "/feedback", json={"thread_id": ask_body["thread_id"], "rating": "up"}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "recorded"

    def test_feedback_on_governed_answer_does_not_create_a_verified_query(
        self, provider, ecommerce_warehouse, embedder
    ):
        """A governed (matched_metric) answer is already fast and
        deterministic -- nothing for the fast path to cache."""
        with DuckDBVSSStore(dim=embedder.dim) as vstore:
            verified_query_store = DuckDBVerifiedQueryStore(vstore, embedder)
            client, llm = _client(
                provider,
                ecommerce_warehouse,
                [SemanticExtraction(time_phrase=None, filters=[])],
                verified_query_store=verified_query_store,
            )
            ask_body = client.post(
                "/ask", json={"dataset_id": "ecommerce", "question": "order count"}
            ).json()

            response = client.post(
                "/feedback", json={"thread_id": ask_body["thread_id"], "rating": "up"}
            )

            assert response.json()["verified_query_created"] is False

    def test_feedback_on_fallback_answer_creates_a_verified_query(
        self, provider, ecommerce_warehouse, embedder
    ):
        with DuckDBVSSStore(dim=embedder.dim) as vstore:
            verified_query_store = DuckDBVerifiedQueryStore(vstore, embedder)
            client, llm = _client(
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
            ask_body = client.post(
                "/ask",
                json={
                    "dataset_id": "ecommerce",
                    "question": "list the distinct discount codes used",
                },
            ).json()
            assert ask_body["kind"] == "answer"

            response = client.post(
                "/feedback", json={"thread_id": ask_body["thread_id"], "rating": "up"}
            )

            assert response.json()["verified_query_created"] is True

    def test_feedback_unknown_thread_404(self, provider, ecommerce_warehouse):
        client, _ = _client(provider, ecommerce_warehouse, [])
        response = client.post("/feedback", json={"thread_id": "nonexistent", "rating": "up"})
        assert response.status_code == 404

    def test_feedback_invalid_rating_422(self, provider, ecommerce_warehouse):
        client, llm = _client(
            provider, ecommerce_warehouse, [SemanticExtraction(time_phrase=None, filters=[])]
        )
        ask_body = client.post(
            "/ask", json={"dataset_id": "ecommerce", "question": "order count"}
        ).json()

        response = client.post(
            "/feedback", json={"thread_id": ask_body["thread_id"], "rating": "sideways"}
        )

        assert response.status_code == 422
