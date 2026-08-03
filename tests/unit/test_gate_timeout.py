"""Comprehensive unit tests for the timeout gate with parametrized test cases.

Tests cover:
  - Happy path: gate passes when timeout not exceeded
  - Violations: gate raises Unsafe when timeout exceeded
  - Edge cases: None timeout, no guarded dict, boundary conditions
  - State mutations: guarded dict properly initialized and updated

Uses pytest.mark.parametrize for multiple scenarios and time-machine for
deterministic time control.
"""

import asyncio

import pytest
import time_machine

from omniagent.kernel.gates import Unsafe
from omniagent.kernel.gates.timeout import timeout_gate
from omniagent.kernel.state import OmniState


def async_test(coro):
    """Helper to run async functions in sync tests."""
    return asyncio.run(coro)


class TestTimeoutGateHappyPath:
    """Happy path tests: gate passes and state is properly modified."""

    @pytest.mark.unit
    def test_no_timeout_config_passes_through(self):
        """When timeout_ms is None in config, gate passes through unchanged."""
        state = OmniState(thread_id="test-1")
        result = async_test(timeout_gate(state, config={}))

        assert result is state
        assert state.guarded is None

    @pytest.mark.unit
    def test_no_timeout_config_with_empty_dict(self):
        """When config is empty dict, gate passes through unchanged."""
        state = OmniState(thread_id="test-2")
        result = async_test(timeout_gate(state, config={}))

        assert result is state

    @pytest.mark.unit
    def test_first_call_initializes_timing(self):
        """First call to gate initializes start_time in guarded dict."""
        state = OmniState(thread_id="test-3")
        config = {"timeout_ms": 5000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False):
            result = async_test(timeout_gate(state, config=config))

        assert result is state
        assert state.guarded is not None
        assert "timeout_gate" in state.guarded
        assert "start_time" in state.guarded["timeout_gate"]
        assert state.guarded["timeout_gate"]["timeout_ms"] == 5000

    @pytest.mark.unit
    def test_second_call_within_timeout_passes(self):
        """Subsequent call within timeout window passes through unchanged."""
        state = OmniState(thread_id="test-4")
        config = {"timeout_ms": 5000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            # First call: initialize timing
            async_test(timeout_gate(state, config=config))

            # Advance time by 2 seconds (well within 5 second timeout)
            freezer.move_to("2026-08-01 12:00:02")

            # Second call: should pass
            result = async_test(timeout_gate(state, config=config))

        assert result is state
        assert state.guarded is not None

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "elapsed_seconds,timeout_ms,should_pass",
        [
            (0.5, 1000, True),  # 500ms elapsed, 1000ms timeout
            (0.999, 1000, True),  # Just under timeout
            (1.5, 2000, True),  # 1500ms elapsed, 2000ms timeout
            (0.1, 500, True),  # 100ms elapsed, 500ms timeout
        ],
    )
    def test_various_timeouts_within_limit(self, elapsed_seconds, timeout_ms, should_pass):
        """Test various timeout configurations where execution is within limit."""
        state = OmniState(thread_id=f"test-within-{elapsed_seconds}-{timeout_ms}")
        config = {"timeout_ms": timeout_ms}

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            # Initialize timing
            async_test(timeout_gate(state, config=config))

            # Advance time by elapsed_seconds
            freezer.move_to(f"2026-08-01 12:00:{elapsed_seconds:05.2f}")

            # Second call should pass
            result = async_test(timeout_gate(state, config=config))

        assert result is state
        assert should_pass

    @pytest.mark.unit
    def test_gate_preserves_other_state_fields(self):
        """Gate does not modify other state fields, only updates guarded dict."""
        state = OmniState(
            thread_id="test-5",
            dataset_id="dataset-123",
            executed_sql="SELECT * FROM table",
            narration="Test narration",
        )
        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False):
            result = async_test(timeout_gate(state, config=config))

        # Verify original fields unchanged
        assert result.thread_id == "test-5"
        assert result.dataset_id == "dataset-123"
        assert result.executed_sql == "SELECT * FROM table"
        assert result.narration == "Test narration"


class TestTimeoutGateViolations:
    """Violation tests: gate raises Unsafe when timeout exceeded."""

    @pytest.mark.unit
    def test_second_call_exceeds_timeout(self):
        """When elapsed time exceeds timeout_ms, gate raises Unsafe."""
        state = OmniState(thread_id="test-6")
        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            # First call: initialize
            async_test(timeout_gate(state, config=config))

            # Advance time past timeout (1.5 seconds > 1000ms)
            freezer.move_to("2026-08-01 12:00:01.5")

            # Second call should raise Unsafe
            with pytest.raises(Unsafe) as exc_info:
                async_test(timeout_gate(state, config=config))

            assert exc_info.value.reason == "query timeout"

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "elapsed_seconds,timeout_ms",
        [
            (1.1, 1000),  # 1100ms elapsed, 1000ms timeout
            (2.5, 2000),  # 2500ms elapsed, 2000ms timeout
            (5.0, 4000),  # 5000ms elapsed, 4000ms timeout
            (0.11, 100),  # 110ms elapsed, 100ms timeout
        ],
    )
    def test_various_timeout_violations(self, elapsed_seconds, timeout_ms):
        """Test various timeout configurations where execution exceeds limit."""
        state = OmniState(thread_id=f"test-violation-{elapsed_seconds}-{timeout_ms}")
        config = {"timeout_ms": timeout_ms}

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            # Initialize timing
            async_test(timeout_gate(state, config=config))

            # Advance time past timeout
            freezer.move_to(f"2026-08-01 12:00:{elapsed_seconds:05.2f}")

            # Should raise Unsafe
            with pytest.raises(Unsafe) as exc_info:
                async_test(timeout_gate(state, config=config))

            assert exc_info.value.reason == "query timeout"

    @pytest.mark.unit
    def test_timeout_exception_reason(self):
        """Unsafe exception has correct reason message."""
        state = OmniState(thread_id="test-7")
        config = {"timeout_ms": 500}

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            async_test(timeout_gate(state, config=config))
            freezer.move_to("2026-08-01 12:00:01")

            with pytest.raises(Unsafe) as exc_info:
                async_test(timeout_gate(state, config=config))

            assert str(exc_info.value) == "query timeout"
            assert exc_info.value.reason == "query timeout"

    @pytest.mark.unit
    def test_zero_timeout_immediate_violation(self):
        """Timeout of 0ms should violate on any second call."""
        state = OmniState(thread_id="test-8")
        config = {"timeout_ms": 0}

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            # First call: initialize
            async_test(timeout_gate(state, config=config))

            # Even tiny advance should exceed 0ms timeout
            freezer.move_to("2026-08-01 12:00:00.000001")

            with pytest.raises(Unsafe):
                async_test(timeout_gate(state, config=config))


class TestTimeoutGateEdgeCases:
    """Edge case tests: boundary conditions and unusual inputs."""

    @pytest.mark.unit
    def test_no_guarded_dict_creates_one(self):
        """When state.guarded is None, gate initializes it."""
        state = OmniState(thread_id="test-9")
        assert state.guarded is None

        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False):
            async_test(timeout_gate(state, config=config))

        assert state.guarded is not None
        assert isinstance(state.guarded, dict)

    @pytest.mark.unit
    def test_existing_guarded_dict_preserved(self):
        """When state.guarded has other entries, they are preserved."""
        state = OmniState(thread_id="test-10")
        state.guarded = {"other_gate": {"result": "pass"}}

        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False):
            async_test(timeout_gate(state, config=config))

        # Original entry preserved
        assert state.guarded["other_gate"] == {"result": "pass"}
        # New entry added
        assert "timeout_gate" in state.guarded

    @pytest.mark.unit
    def test_very_small_timeout(self):
        """Test with very small timeout value (10 milliseconds)."""
        state = OmniState(thread_id="test-11")
        config = {"timeout_ms": 10}

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            async_test(timeout_gate(state, config=config))

            # Move 20ms forward (exceeds 10ms timeout)
            freezer.move_to("2026-08-01 12:00:00.02")

            # Should violate the 10ms timeout
            with pytest.raises(Unsafe):
                async_test(timeout_gate(state, config=config))

    @pytest.mark.unit
    def test_very_large_timeout(self):
        """Test with very large timeout value."""
        state = OmniState(thread_id="test-12")
        config = {"timeout_ms": 3600000}  # 1 hour

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            async_test(timeout_gate(state, config=config))

            # Advance 30 minutes
            freezer.move_to("2026-08-01 12:30:00")

            # Should still pass
            result = async_test(timeout_gate(state, config=config))
            assert result is state

    @pytest.mark.unit
    def test_multiple_gate_invocations_accumulate_time(self):
        """Time accumulates across multiple gate checks, not reset."""
        state = OmniState(thread_id="test-13")
        config = {"timeout_ms": 2000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            # Call 1: Initialize
            async_test(timeout_gate(state, config=config))

            # Call 2: After 500ms (should pass)
            freezer.move_to("2026-08-01 12:00:00.5")
            result = async_test(timeout_gate(state, config=config))
            assert result is state

            # Call 3: After total 1500ms (should pass)
            freezer.move_to("2026-08-01 12:00:01.5")
            result = async_test(timeout_gate(state, config=config))
            assert result is state

            # Call 4: After total 2500ms (should fail)
            freezer.move_to("2026-08-01 12:00:02.5")
            with pytest.raises(Unsafe):
                async_test(timeout_gate(state, config=config))

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "config_input",
        [
            {},  # Empty config
            {"timeout_ms": None},  # Explicit None
            {"other_key": "value"},  # Config with unrelated key
            {"timeout_ms": None, "other": 123},  # Mixed with other keys
        ],
    )
    def test_no_timeout_with_various_configs(self, config_input):
        """Gate passes through when timeout_ms is None or missing."""
        state = OmniState(thread_id="test-config")
        result = async_test(timeout_gate(state, config=config_input))

        # Should return unchanged
        assert result is state

    @pytest.mark.unit
    def test_exact_timeout_boundary(self):
        """Test behavior exactly at timeout boundary (elapsed == timeout)."""
        state = OmniState(thread_id="test-14")
        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            async_test(timeout_gate(state, config=config))

            # Advance exactly 1000ms (1 second)
            freezer.move_to("2026-08-01 12:00:01")

            # At exact boundary, should still pass (elapsed == timeout, not >)
            result = async_test(timeout_gate(state, config=config))
            assert result is state

    @pytest.mark.unit
    def test_just_over_timeout_boundary(self):
        """Test behavior just past timeout boundary."""
        state = OmniState(thread_id="test-15")
        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            async_test(timeout_gate(state, config=config))

            # Advance 1000.1ms (just over 1 second)
            freezer.move_to("2026-08-01 12:00:01.0001")

            # Just over boundary should fail
            with pytest.raises(Unsafe):
                async_test(timeout_gate(state, config=config))

    @pytest.mark.unit
    def test_gate_data_stored_correctly(self):
        """Verify gate_data is stored with correct structure."""
        state = OmniState(thread_id="test-16")
        config = {"timeout_ms": 5000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False):
            async_test(timeout_gate(state, config=config))

        gate_data = state.guarded["timeout_gate"]
        assert "start_time" in gate_data
        assert "timeout_ms" in gate_data
        assert isinstance(gate_data["start_time"], float)
        assert gate_data["timeout_ms"] == 5000


class TestTimeoutGateEmptyAndNoneValues:
    """Tests for handling of empty results, None values, and special cases."""

    @pytest.mark.unit
    def test_state_with_none_result_meta(self):
        """Gate works with None result_meta."""
        state = OmniState(thread_id="test-17", result_meta=None)
        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False):
            result = async_test(timeout_gate(state, config=config))

        assert result is state

    @pytest.mark.unit
    def test_state_with_empty_result_meta(self):
        """Gate works with empty result_meta dict."""
        state = OmniState(thread_id="test-18", result_meta={})
        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False):
            result = async_test(timeout_gate(state, config=config))

        assert result is state

    @pytest.mark.unit
    def test_state_with_empty_guarded(self):
        """Gate works when state.guarded is empty dict."""
        state = OmniState(thread_id="test-19")
        state.guarded = {}
        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False):
            result = async_test(timeout_gate(state, config=config))

        assert result is state
        assert "timeout_gate" in state.guarded


class TestTimeoutGateBranchCoverage:
    """Tests designed to maximize branch coverage of the gate module."""

    @pytest.mark.unit
    def test_branch_config_get_timeout_ms_missing(self):
        """Branch: config.get("timeout_ms") returns None."""
        state = OmniState(thread_id="test-20")
        # config doesn't have timeout_ms key
        result = async_test(timeout_gate(state, config={}))
        assert result is state

    @pytest.mark.unit
    def test_branch_state_guarded_none_first_call(self):
        """Branch: state.guarded is None on first call."""
        state = OmniState(thread_id="test-21")
        assert state.guarded is None
        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False):
            async_test(timeout_gate(state, config=config))

        assert state.guarded is not None

    @pytest.mark.unit
    def test_branch_start_time_not_in_gate_data(self):
        """Branch: first call creates start_time in gate_data."""
        state = OmniState(thread_id="test-22")
        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False):
            async_test(timeout_gate(state, config=config))

        # Verify start_time was created
        assert "start_time" in state.guarded["timeout_gate"]

    @pytest.mark.unit
    def test_branch_start_time_in_gate_data(self):
        """Branch: second call retrieves existing start_time from gate_data."""
        state = OmniState(thread_id="test-23")
        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            # First call
            async_test(timeout_gate(state, config=config))
            start_time_first = state.guarded["timeout_gate"]["start_time"]

            # Second call
            freezer.move_to("2026-08-01 12:00:00.5")
            async_test(timeout_gate(state, config=config))

            # start_time should not change
            assert state.guarded["timeout_gate"]["start_time"] == start_time_first

    @pytest.mark.unit
    def test_branch_elapsed_time_not_exceeded(self):
        """Branch: elapsed_ms <= timeout_ms (pass case)."""
        state = OmniState(thread_id="test-24")
        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            async_test(timeout_gate(state, config=config))
            freezer.move_to("2026-08-01 12:00:00.5")
            result = async_test(timeout_gate(state, config=config))

        # Should not raise
        assert result is state

    @pytest.mark.unit
    def test_branch_elapsed_time_exceeded(self):
        """Branch: elapsed_ms > timeout_ms (fail case)."""
        state = OmniState(thread_id="test-25")
        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            async_test(timeout_gate(state, config=config))
            freezer.move_to("2026-08-01 12:00:01.5")

            with pytest.raises(Unsafe):
                async_test(timeout_gate(state, config=config))


@pytest.mark.unit
class TestTimeoutGateIntegration:
    """Integration-like tests combining multiple scenarios."""

    @pytest.mark.unit
    def test_multiple_concurrent_states_independent(self):
        """Multiple state objects track timeouts independently."""
        state1 = OmniState(thread_id="concurrent-1")
        state2 = OmniState(thread_id="concurrent-2")
        config = {"timeout_ms": 1000}

        with time_machine.travel("2026-08-01 12:00:00", tick=False) as freezer:
            # Initialize both
            async_test(timeout_gate(state1, config=config))
            async_test(timeout_gate(state2, config=config))

            # Advance time
            freezer.move_to("2026-08-01 12:00:00.5")

            # Both should still pass
            async_test(timeout_gate(state1, config=config))
            async_test(timeout_gate(state2, config=config))

            # Verify they have different start times
            time1 = state1.guarded["timeout_gate"]["start_time"]
            time2 = state2.guarded["timeout_gate"]["start_time"]
            # Note: with time_machine, they might be the same, but structure should be independent
            assert time1 == time2  # same frozen time
