"""Integration tests for clarify_node: interrupt()-based pause and resume.

interrupt() can only be exercised meaningfully through a real compiled
graph with a checkpointer -- there is no way to unit-test it against a
bare node function, since pausing and resuming is a property of the
graph run, not of the node in isolation.
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from omniagent.agents.clarify import make_clarify_node
from omniagent.agents.master import make_master_node
from omniagent.kernel.catalog import Catalog, MetricInfo
from omniagent.kernel.state import OmniState


def _tied_catalog() -> Catalog:
    return Catalog(
        dataset_id="test",
        metrics={
            "metric_a": MetricInfo(name="metric_a", label="Order count", synonyms=("order total",)),
            "metric_b": MetricInfo(name="metric_b", label="Order value", synonyms=("order total",)),
        },
    )


def _build_graph(catalog: Catalog, *, fallback_route: str | None = None):
    async def landed(state: OmniState) -> dict:
        return {"narration": f"landed with matched_metric={state.matched_metric}"}

    async def fast_path_stub(state: OmniState) -> dict:
        return {"narration": "reached fast_path stub"}

    builder: StateGraph = StateGraph(OmniState)
    builder.add_node("master", make_master_node(catalog, clarify_route="clarify"))
    builder.add_node("clarify", make_clarify_node(catalog=catalog, fallback_route=fallback_route))
    builder.add_node("semantic_agent", landed)
    builder.add_node("fast_path", fast_path_stub)
    builder.add_edge(START, "master")
    builder.add_edge("semantic_agent", END)
    builder.add_edge("fast_path", END)
    return builder.compile(checkpointer=InMemorySaver())


@pytest.mark.integration
class TestClarifyNodeInterruptResume:
    async def test_ambiguous_question_pauses_with_clarification_options(self):
        graph = _build_graph(_tied_catalog())
        config = {"configurable": {"thread_id": "t1"}}

        result = await graph.ainvoke(
            OmniState(thread_id="t1", messages=[{"role": "user", "content": "order total"}]),
            config,
        )

        assert "__interrupt__" in result
        value = result["__interrupt__"][0].value
        assert value["question"] == "Which metric did you mean?"
        assert set(value["options"]) == {"Order count", "Order value"}

    async def test_resume_with_a_valid_option_reaches_the_matched_node(self):
        graph = _build_graph(_tied_catalog())
        config = {"configurable": {"thread_id": "t2"}}

        await graph.ainvoke(
            OmniState(thread_id="t2", messages=[{"role": "user", "content": "order total"}]),
            config,
        )
        result = await graph.ainvoke(Command(resume="Order count"), config)

        assert result.get("error") is None
        assert "__interrupt__" not in result
        assert result["narration"] == "landed with matched_metric=metric_a"

    async def test_resumed_answer_is_recorded_as_a_real_user_message(self):
        graph = _build_graph(_tied_catalog())
        config = {"configurable": {"thread_id": "t3"}}

        await graph.ainvoke(
            OmniState(thread_id="t3", messages=[{"role": "user", "content": "order total"}]),
            config,
        )
        result = await graph.ainvoke(Command(resume="Order count"), config)

        contents = [m["content"] for m in result["messages"]]
        assert contents == ["order total", "Order count"]

    async def test_still_ambiguous_answer_pauses_again_via_the_same_node(self):
        """A resumed answer that itself ties between the same two metrics
        (e.g. the user retyped the original ambiguous phrase) comes right
        back through clarify for another round, not a dead end."""
        graph = _build_graph(_tied_catalog())
        config = {"configurable": {"thread_id": "t4"}}

        await graph.ainvoke(
            OmniState(thread_id="t4", messages=[{"role": "user", "content": "order total"}]),
            config,
        )
        result = await graph.ainvoke(Command(resume="order total"), config)

        assert "__interrupt__" in result
        assert set(result["__interrupt__"][0].value["options"]) == {"Order count", "Order value"}

    async def test_resume_with_an_unrecognized_answer_and_no_fallback_ends_with_plain_clarification(
        self,
    ):
        graph = _build_graph(_tied_catalog(), fallback_route=None)
        config = {"configurable": {"thread_id": "t5"}}

        await graph.ainvoke(
            OmniState(thread_id="t5", messages=[{"role": "user", "content": "order total"}]),
            config,
        )
        result = await graph.ainvoke(Command(resume="what is the meaning of life"), config)

        assert "__interrupt__" not in result
        assert result["needs_human"] is True
        assert result["route"] == "clarify"

    async def test_resume_with_an_unrecognized_answer_falls_through_to_configured_fallback(self):
        graph = _build_graph(_tied_catalog(), fallback_route="fast_path")
        config = {"configurable": {"thread_id": "t6"}}

        await graph.ainvoke(
            OmniState(thread_id="t6", messages=[{"role": "user", "content": "order total"}]),
            config,
        )
        result = await graph.ainvoke(Command(resume="what is the meaning of life"), config)

        assert "__interrupt__" not in result
        assert result["route"] == "fast_path"
