"""Integration tests for the FastAPI service: real graph, real DuckDB
warehouse fixture, ScriptedLLM — every endpoint exercised through an
actual HTTP-shaped TestClient request/response cycle."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
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
from omniagent.kernel.models import SemanticExtraction
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


def _client(provider, engine, script):
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
    runtime = DatasetRuntime(
        dataset_id="ecommerce",
        label="E-commerce",
        description="Test dataset",
        catalog=catalog,
        graph=graph,
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
        client, llm = _client(provider, ecommerce_warehouse, [])
        response = client.post(
            "/ask", json={"dataset_id": "ecommerce", "question": "what's the weather"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["kind"] == "clarification"
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


@pytest.mark.integration
class TestResume:
    def test_resume_continues_existing_thread(self, provider, ecommerce_warehouse):
        client, llm = _client(
            provider,
            ecommerce_warehouse,
            [
                SemanticExtraction(time_phrase=None, filters=[]),
                SemanticExtraction(time_phrase=None, filters=[]),
            ],
        )
        ask_body = client.post(
            "/ask", json={"dataset_id": "ecommerce", "question": "order count"}
        ).json()

        resume_response = client.post(
            "/resume", json={"thread_id": ask_body["thread_id"], "message": "gross revenue"}
        )

        assert resume_response.status_code == 200
        resume_body = resume_response.json()
        assert resume_body["thread_id"] == ask_body["thread_id"]
        assert resume_body["narration"] == "Gross revenue was $225.00."

    def test_resume_unknown_thread_404(self, provider, ecommerce_warehouse):
        client, _ = _client(provider, ecommerce_warehouse, [])
        response = client.post("/resume", json={"thread_id": "nonexistent", "message": "x"})
        assert response.status_code == 404


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
