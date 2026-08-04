"""Streamlit UI: consumes only the FastAPI service's public HTTP API.

No shortcut into the graph, the catalog, or the engine — everything this
app can do, any other channel (CLI, MCP, a future native client) can do
through the same four endpoints. That is the whole point of putting a
service layer in front of the graph at all.

Run:
    streamlit run omniagent/channels/streamlit_app.py
    (with the API already running: python scripts/serve.py)
"""

from __future__ import annotations

import os
from typing import Any, cast

import requests
import streamlit as st

API_BASE_URL = os.getenv("OMNIAGENT_API_URL", "http://localhost:8000")
_REQUEST_TIMEOUT_S = 30

st.set_page_config(page_title="OmniAgent", page_icon="✳️", layout="centered")


# ---------------------------------------------------------------------------
# API client — thin wrappers, no logic beyond the HTTP call itself.
# ---------------------------------------------------------------------------


def _get(path: str) -> Any:
    response = requests.get(f"{API_BASE_URL}{path}", timeout=_REQUEST_TIMEOUT_S)
    response.raise_for_status()
    return response.json()


def _post(path: str, body: dict[str, Any]) -> Any:
    response = requests.post(f"{API_BASE_URL}{path}", json=body, timeout=_REQUEST_TIMEOUT_S)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=60)
def fetch_datasets() -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", _get("/datasets"))


def ask(dataset_id: str, question: str, thread_id: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {"dataset_id": dataset_id, "question": question}
    if thread_id:
        body["thread_id"] = thread_id
    return cast("dict[str, Any]", _post("/ask", body))


def resume(thread_id: str, message: str) -> dict[str, Any]:
    return cast("dict[str, Any]", _post("/resume", {"thread_id": thread_id, "message": message}))


def send_feedback(thread_id: str, rating: str) -> None:
    _post("/feedback", {"thread_id": thread_id, "rating": rating})


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


def _init_state() -> None:
    st.session_state.setdefault("dataset_id", None)
    st.session_state.setdefault("thread_id", None)
    st.session_state.setdefault("turns", [])  # list of {question, envelope}
    st.session_state.setdefault("pending_question", None)


def _reset_thread() -> None:
    st.session_state["thread_id"] = None
    st.session_state["turns"] = []


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_answer_card(  # noqa: C901 - a linear sequence of render steps, one per envelope field
    question: str, envelope: dict[str, Any], turn_index: int
) -> None:
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        if envelope["kind"] == "clarification":
            st.info(envelope["narration"])
            options = (envelope.get("clarification") or {}).get("options", [])
            cols = st.columns(min(len(options), 4) or 1)
            for i, option in enumerate(options[:8]):
                with cols[i % len(cols)]:
                    if st.button(option, key=f"clarify-{turn_index}-{i}"):
                        st.session_state["pending_question"] = option
                        st.rerun()
            return

        if envelope["kind"] == "abstention":
            st.warning(f"I couldn't answer that: {envelope['narration']}")
            return

        values = envelope.get("values") or []
        if len(values) == 1 and not envelope.get("chart"):
            # Single KPI: a stat tile, not a one-bar chart — per the
            # "is it even a chart?" rule (a single number is a metric, not
            # a plot).
            metric = values[0]
            st.metric(label=envelope.get("headline") or metric["metric"], value=metric["value"])
        else:
            st.markdown(f"### {envelope.get('headline') or ''}")

        if envelope.get("narration"):
            st.write(envelope["narration"])

        chart = envelope.get("chart")
        rows = envelope.get("rows")
        if chart and rows:
            spec = {
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "data": {"values": rows},
                "mark": chart["mark"],
                "encoding": chart["encoding"],
                "title": chart.get("title", ""),
            }
            st.vega_lite_chart(spec, width="stretch")

        if rows and len(rows) > 1:
            with st.expander(f"Data ({len(rows)} rows)"):
                st.dataframe(rows, width="stretch")

        confidence = envelope.get("confidence")
        if confidence is not None:
            badge = "🟢" if confidence >= 0.85 else "🟡" if confidence >= 0.6 else "🔴"
            st.caption(f"{badge} Confidence: {confidence:.0%}")

        for assumption in envelope.get("assumptions") or []:
            st.caption(f"ℹ️ {assumption}")

        if envelope.get("executed_sql"):
            with st.expander("Show SQL"):
                st.code(envelope["executed_sql"], language="sql")

        thread_id = str(envelope.get("thread_id") or "")
        col_up, col_down, _ = st.columns([1, 1, 6])
        with col_up:
            if st.button("👍", key=f"up-{turn_index}"):
                send_feedback(thread_id, "up")
                st.toast("Thanks for the feedback!")
        with col_down:
            if st.button("👎", key=f"down-{turn_index}"):
                send_feedback(thread_id, "down")
                st.toast("Thanks — noted.")

        suggestions = envelope.get("suggestions") or []
        if suggestions:
            st.caption("Try next:")
            cols = st.columns(min(len(suggestions), 3))
            for i, suggestion in enumerate(suggestions):
                with cols[i % len(cols)]:
                    if st.button(suggestion, key=f"suggest-{turn_index}-{i}"):
                        st.session_state["pending_question"] = suggestion
                        st.rerun()


def render_starter_chips(starters: list[str]) -> None:
    st.caption("Try asking:")
    cols = st.columns(min(len(starters), 4) or 1)
    for i, question in enumerate(starters):
        with cols[i % len(cols)]:
            if st.button(question, key=f"starter-{i}", width="stretch"):
                st.session_state["pending_question"] = question
                st.rerun()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def main() -> None:
    _init_state()

    st.title("✳️ OmniAgent")
    st.caption("A governed answer engine — deterministic gates, no guessed numbers.")

    try:
        datasets = fetch_datasets()
    except requests.RequestException:
        st.error(
            f"Can't reach the API at {API_BASE_URL}. Start it with `python scripts/serve.py` first."
        )
        return

    if not datasets:
        st.warning("No datasets available.")
        return

    dataset_labels = {d["dataset_id"]: d["label"] for d in datasets}
    dataset_by_id = {d["dataset_id"]: d for d in datasets}

    with st.sidebar:
        st.subheader("Dataset")
        selected = st.selectbox(
            "Choose a dataset",
            options=list(dataset_labels),
            format_func=lambda k: dataset_labels[k],
            index=0 if st.session_state["dataset_id"] is None else None,
            key="dataset_select",
        )
        if selected != st.session_state["dataset_id"]:
            st.session_state["dataset_id"] = selected
            _reset_thread()
        st.caption(dataset_by_id[selected]["description"])
        if st.button("New conversation"):
            _reset_thread()
            st.rerun()

    dataset_id = st.session_state["dataset_id"]

    for i, turn in enumerate(st.session_state["turns"]):
        render_answer_card(turn["question"], turn["envelope"], i)

    if not st.session_state["turns"]:
        render_starter_chips(dataset_by_id[dataset_id]["starter_questions"])

    question = st.session_state.pop("pending_question", None) or st.chat_input(
        "Ask a question about your data..."
    )

    if question:
        thread_id = st.session_state["thread_id"]
        with st.spinner("Thinking..."):
            envelope = resume(thread_id, question) if thread_id else ask(dataset_id, question, None)
        st.session_state["thread_id"] = envelope.get("thread_id")
        st.session_state["turns"].append({"question": question, "envelope": envelope})
        st.rerun()


if __name__ == "__main__":
    main()
