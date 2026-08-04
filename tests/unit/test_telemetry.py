"""Unit tests for kernel/telemetry.py: masking and span recording."""

import pytest
from langgraph.errors import GraphInterrupt
from langgraph.types import Interrupt

from omniagent.kernel.telemetry import Tracer, mask_value


class TestMaskValue:
    def test_masks_an_email_address(self):
        assert mask_value("contact bob@example.com") == "contact ***@***"

    def test_masks_a_long_digit_run(self):
        assert mask_value("card 4111111111111111 expires") == "card *** expires"

    def test_short_digit_runs_are_not_masked(self):
        assert mask_value("only 3 items") == "only 3 items"

    def test_recurses_into_dict_values(self):
        assert mask_value({"q": "jane@example.com", "n": 5}) == {"q": "***@***", "n": 5}

    def test_recurses_into_list_values(self):
        assert mask_value(["a@b.com", 42]) == ["***@***", 42]

    def test_recurses_into_tuple_values_preserving_type(self):
        result = mask_value(("a@b.com", 1))
        assert result == ("***@***", 1)
        assert isinstance(result, tuple)

    def test_non_string_leaves_pass_through_unchanged(self):
        flag = True
        assert mask_value(42) == 42
        assert mask_value(None) is None
        assert mask_value(3.14) == 3.14
        assert mask_value(flag) is True

    def test_nested_structures_are_masked_at_every_level(self):
        value = {"messages": [{"role": "user", "content": "email me at x@y.com"}]}
        masked = mask_value(value)
        assert masked["messages"][0]["content"] == "email me at ***@***"


class TestTracer:
    def test_records_a_span_with_masked_inputs(self):
        tracer = Tracer(thread_id="t1")
        with tracer.span("master", question="net revenue for jane@example.com"):
            pass

        assert len(tracer.trace.spans) == 1
        span = tracer.trace.spans[0]
        assert span.name == "master"
        assert span.inputs["question"] == "net revenue for ***@***"
        assert span.error is None
        assert span.duration_ms >= 0

    def test_records_multiple_spans_in_order(self):
        tracer = Tracer(thread_id="t1")
        with tracer.span("master"):
            pass
        with tracer.span("executor"):
            pass

        assert [span.name for span in tracer.trace.spans] == ["master", "executor"]

    def test_records_the_error_and_still_re_raises(self):
        tracer = Tracer(thread_id="t1")
        with pytest.raises(ValueError, match="boom"):
            with tracer.span("executor"):
                raise ValueError("boom")

        assert tracer.trace.spans[0].error == "boom"
        assert tracer.trace.spans[0].paused is False

    def test_a_graph_interrupt_is_recorded_as_paused_not_errored(self):
        """interrupt()-based pauses (agents/clarify.py) are a deliberate,
        successful control-flow event, not a failure -- `error` must stay
        None so a paused span never reads like something went wrong."""
        tracer = Tracer(thread_id="t1")
        with pytest.raises(GraphInterrupt):
            with tracer.span("clarify"):
                raise GraphInterrupt([Interrupt(value={"question": "?"}, id="i1")])

        span = tracer.trace.spans[0]
        assert span.paused is True
        assert span.error is None

    def test_trace_is_scoped_to_its_own_thread_id(self):
        tracer_a = Tracer(thread_id="a")
        tracer_b = Tracer(thread_id="b")
        with tracer_a.span("master"):
            pass

        assert len(tracer_a.trace.spans) == 1
        assert len(tracer_b.trace.spans) == 0
        assert tracer_a.trace.thread_id == "a"
        assert tracer_b.trace.thread_id == "b"
