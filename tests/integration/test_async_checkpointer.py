"""Regression test for a real bug Phase 11's Docker packaging work found:
`SqliteSaver` (the checkpointer scripts/serve.py originally wired up) does
not implement its async methods at all, so a real `uvicorn`-served
`/ask`/`/resume` call (`ainvoke`, `aget_state`) raised `NotImplementedError`
on the very first request. Every prior test used the async-native
`InMemorySaver`, which is why this was never caught until the composition
root actually ran under a real ASGI server.

This exercises `scripts.serve.open_checkpointer` directly against a real
graph and a real `TestClient` (which drives FastAPI's actual startup/
shutdown lifespan, exactly like a real ASGI server would), rather than
mocking anything about the checkpointer.
"""

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
from scripts.serve import open_checkpointer
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


@pytest.mark.integration
async def test_open_checkpointer_supports_the_async_methods_a_real_server_calls(tmp_path):
    """The exact operations `/ask` and `/resume` call (`aget_tuple`, and by
    extension `ainvoke`/`aget_state`) must not raise `NotImplementedError`."""
    async with open_checkpointer(tmp_path / "checkpoints.sqlite") as checkpointer:
        config = {"configurable": {"thread_id": "t1"}}
        tup = await checkpointer.aget_tuple(config)
        assert tup is None


@pytest.mark.integration
def test_real_asgi_lifespan_builds_datasets_and_serves_a_real_ask_call(
    tmp_path, ecommerce_warehouse
):
    """Drives `create_app`'s `lifespan` parameter through `TestClient`'s
    real ASGI startup/shutdown, the same protocol a real `uvicorn` server
    uses -- proving the checkpointer's connection stays usable across an
    actual request, not just at construction time."""
    provider = NativeYamlProvider("packs")
    catalog = provider.catalog("ecommerce")
    llm = ScriptedLLM([SemanticExtraction(time_phrase=None, filters=[])])

    datasets: dict[str, DatasetRuntime] = {}

    async def lifespan(_app):
        async with open_checkpointer(tmp_path / "checkpoints.sqlite") as checkpointer:
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
                checkpointer=checkpointer,
            )
            datasets["ecommerce"] = DatasetRuntime(
                dataset_id="ecommerce",
                label="E-commerce",
                description="Test dataset",
                catalog=catalog,
                graph=graph,
                schema_version=provider.schema_version("ecommerce"),
            )
            yield

    app = create_app(datasets, lifespan=lifespan)

    with TestClient(app) as client:
        response = client.post(
            "/ask", json={"dataset_id": "ecommerce", "question": "gross revenue"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "answer"
    assert body["narration"] == "Gross revenue was $225.00."
    llm.assert_call_count(1)
