"""E2E tests for the Streamlit UI: real running FastAPI service (ephemeral
port, real graph, real DuckDB, ScriptedLLM) driven through Streamlit's
AppTest framework — the full click-through path a user takes, without a
mocked API layer.
"""

import threading
import time

import pytest
import uvicorn

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
from omniagent.kernel.time_resolver import DefaultTimeResolver
from tests.fakes.llm import ScriptedLLM

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

APP_PATH = "omniagent/channels/streamlit_app.py"


@pytest.fixture
def provider():
    return NativeYamlProvider("packs")


@pytest.fixture
def live_service_url(provider, ecommerce_warehouse, monkeypatch):
    """A real FastAPI service on an ephemeral port, backed by an
    infinitely-repeating ScriptedLLM so click-through tests aren't limited
    to a fixed call count."""
    catalog = provider.catalog("ecommerce")

    class RepeatingScriptedLLM(ScriptedLLM):
        def __init__(self):
            super().__init__([], max_calls=1000)

        def structured(self, model_id, req, schema):
            self.calls.append({"model": model_id, "req": req})
            return schema(time_phrase=None, filters=[])

    llm = RepeatingScriptedLLM()
    graph = build_governed_graph(
        dataset_id="ecommerce",
        catalog=catalog,
        semantic_provider=provider,
        engine=ecommerce_warehouse,
        llm=llm,
        model_id="test-model",
        time_resolver=DefaultTimeResolver(),
        guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
    )
    runtime = DatasetRuntime(
        dataset_id="ecommerce",
        label="E-commerce",
        description="Test dataset",
        catalog=catalog,
        graph=graph,
    )
    app = create_app({"ecommerce": runtime})

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started, "uvicorn server failed to start within 5s"

    port = server.servers[0].sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("OMNIAGENT_API_URL", url)

    yield url

    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.e2e
class TestStreamlitClickThrough:
    def test_initial_load_shows_dataset_and_starters(self, live_service_url):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()

        assert not at.exception
        assert at.title[0].value == "✳️ OmniAgent"
        assert at.sidebar.selectbox[0].options == ["E-commerce"]
        starter_labels = {b.label for b in at.button if b.key and b.key.startswith("starter-")}
        assert "Gross revenue" in starter_labels

    def test_starter_chip_click_renders_stat_tile(self, live_service_url):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()

        starter = [b for b in at.button if b.label == "Gross revenue"][0]
        starter.click().run()

        assert not at.exception
        assert len(at.metric) == 1
        assert at.metric[0].value == "225.0"

    def test_breakdown_question_renders_chart_and_table(self, live_service_url):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()

        at.chat_input[0].set_value("gross revenue by channel").run()

        assert not at.exception
        assert len(at.session_state["turns"]) == 1
        envelope = at.session_state["turns"][0]["envelope"]
        assert envelope["chart"]["mark"] == "bar"

    def test_followup_suggestion_continues_same_thread(self, live_service_url):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()

        starter = [b for b in at.button if b.label == "Gross revenue"][0]
        starter.click().run()
        first_thread_id = at.session_state["thread_id"]

        suggestion_buttons = [b for b in at.button if b.key and b.key.startswith("suggest-0-")]
        assert suggestion_buttons
        suggestion_buttons[0].click().run()

        assert not at.exception
        assert at.session_state["thread_id"] == first_thread_id
        assert len(at.session_state["turns"]) == 2

    def test_feedback_button_does_not_raise(self, live_service_url):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()

        starter = [b for b in at.button if b.label == "Gross revenue"][0]
        starter.click().run()

        thumbs_up = [b for b in at.button if b.label == "👍"][0]
        thumbs_up.click().run()

        assert not at.exception

    def test_unmatched_question_shows_clarification_options(self, live_service_url):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()

        at.chat_input[0].set_value("what is the weather today").run()

        assert not at.exception
        assert len(at.info) == 1
        # The clarification menu caps at 8 options (options[:8] in the app) —
        # the ecommerce catalog has 9 metrics, so the alphabetically-last
        # one (units_sold) is intentionally the one left off.
        clarify_buttons = [b for b in at.button if b.key and b.key.startswith("clarify-0-")]
        assert len(clarify_buttons) == 8
        assert {b.label for b in clarify_buttons} == {
            "Gross revenue",
            "Refunds",
            "Net revenue",
            "Orders",
            "Average order value",
            "Customers",
            "Return rate",
            "Returns",
        }

    def test_clicking_clarification_option_resolves_to_answer(self, live_service_url):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()

        at.chat_input[0].set_value("what is the weather today").run()
        clarify_buttons = [b for b in at.button if b.key and b.key.startswith("clarify-0-")]
        gross_revenue_option = [b for b in clarify_buttons if b.label == "Gross revenue"][0]
        gross_revenue_option.click().run()

        assert not at.exception
        assert len(at.session_state["turns"]) == 2
        assert at.session_state["turns"][1]["envelope"]["kind"] == "answer"
        assert len(at.metric) == 1

    def test_dataset_unreachable_shows_error_not_crash(self, monkeypatch):
        import streamlit as st
        from streamlit.testing.v1 import AppTest

        # fetch_datasets() is @st.cache_data — a process-wide cache, so an
        # earlier test's successful call would otherwise mask this one.
        st.cache_data.clear()
        monkeypatch.setenv("OMNIAGENT_API_URL", "http://127.0.0.1:1")  # nothing listens here
        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()

        assert not at.exception
        assert len(at.error) == 1
