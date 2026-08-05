"""Unit tests for row_cap gate: enforce maximum result set size limits."""

import asyncio

import pytest

from omniagent.kernel.gates.exceptions import Unsafe
from omniagent.kernel.gates.row_cap import row_cap_gate
from omniagent.kernel.state import OmniState


class TestRowCapGateHappyPath:
    """Test cases where the gate passes (row count within limits)."""

    @pytest.mark.parametrize(
        "row_count,max_rows",
        [
            (0, 100),  # Zero rows is always safe
            (1, 100),  # Single row
            (50, 100),  # Half the limit
            (99, 100),  # Just below limit
            (100, 100),  # Exactly at limit
            (1000, 10000),  # Large result set but within limit
            (1, 1),  # Limit of 1 with 1 row
        ],
    )
    @pytest.mark.unit
    def test_row_count_within_limit(self, row_count: int, max_rows: int):
        """Happy path: row count is within max_rows limit."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": row_count},
            assumptions=[],
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": max_rows}))

        # State should be returned unchanged (except guarded and assumptions)
        assert result.result_meta["row_count"] == row_count
        assert result.guarded is not None
        assert result.guarded["row_cap_gate"]["status"] == "within_limit"
        assert result.guarded["row_cap_gate"]["row_count"] == row_count
        assert result.guarded["row_cap_gate"]["max_rows"] == max_rows
        assert result.guarded["row_cap_gate"]["cap_applied"] is False

    @pytest.mark.unit
    def test_no_assumption_added_when_within_limit(self):
        """A result genuinely under the cap is complete -- no caveat about
        it applies, so no boilerplate assumption should be added on every
        single answer regardless of how far under the limit it is."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 50},
            assumptions=[],
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        assert result.assumptions == []

    @pytest.mark.unit
    def test_preexisting_assumptions_untouched_when_within_limit(self):
        """A pre-existing assumption from an earlier gate is left alone."""
        assumption = "Some other gate's assumption"
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 50},
            assumptions=[assumption],
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        assert result.assumptions == [assumption]


class TestRowCapGateViolation:
    """Test cases where the gate rejects (row count exceeds limits)."""

    @pytest.mark.parametrize(
        "row_count,max_rows",
        [
            (101, 100),  # Just over limit
            (1000, 100),  # Way over limit
            (10000, 1000),  # Large overage
            (2, 1),  # Limit of 1 exceeded
            (1000000, 10000),  # Extreme overage
        ],
    )
    @pytest.mark.unit
    def test_row_count_exceeds_limit_raises_unsafe(self, row_count: int, max_rows: int):
        """Violation: row count exceeds max_rows, gate raises Unsafe."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": row_count},
        )

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(row_cap_gate(state, config={"max_rows": max_rows}))

        assert "exceeds max_rows limit" in exc_info.value.reason
        assert str(row_count) in exc_info.value.reason
        assert str(max_rows) in exc_info.value.reason

    @pytest.mark.unit
    def test_violation_error_message_contains_counts(self):
        """Violation: error message includes both row_count and max_rows."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 250},
        )

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        reason = exc_info.value.reason
        assert "250" in reason
        assert "100" in reason


class TestRowCapGateTruncatedSignal:
    """An engine that enforces row_cap at the fetch layer (e.g. DuckDBEngine)
    trims its own returned batch to row_cap before this gate ever runs, so
    row_count can never exceed max_rows by construction when the two caps
    match. `truncated` is the only reliable signal in that case."""

    @pytest.mark.unit
    def test_truncated_true_raises_unsafe_even_if_row_count_within_cap(self):
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 1, "truncated": True},
        )

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(row_cap_gate(state, config={"max_rows": 1}))

        assert "truncated" in exc_info.value.reason.lower()
        assert "1" in exc_info.value.reason

    @pytest.mark.unit
    def test_truncated_false_with_row_count_within_cap_passes(self):
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 1, "truncated": False},
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 1}))

        assert result.guarded["row_cap_gate"]["status"] == "within_limit"

    @pytest.mark.unit
    def test_truncated_absent_falls_back_to_row_count_comparison(self):
        """result_meta without a `truncated` key at all (e.g. hand-built in
        older tests or by an engine that doesn't report it) must not be
        treated as truncated."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 50},
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        assert result.guarded["row_cap_gate"]["status"] == "within_limit"


class TestRowCapGateEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.unit
    def test_no_max_rows_configured(self):
        """Edge case: config has no max_rows key."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 1000000},  # Very large
            assumptions=[],
        )

        result = asyncio.run(row_cap_gate(state, config={}))

        # Should pass through without raising
        assert result.guarded is not None
        assert result.guarded["row_cap_gate"]["status"] == "no_limit_configured"
        assert len(result.assumptions) == 0  # No assumption added

    @pytest.mark.unit
    def test_no_max_rows_none_value(self):
        """Edge case: max_rows is explicitly None in config."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 1000000},
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": None}))

        # Should pass through without raising
        assert result.guarded["row_cap_gate"]["status"] == "no_limit_configured"

    @pytest.mark.unit
    def test_no_result_meta(self):
        """Edge case: state has no result_meta."""
        state = OmniState(thread_id="test_thread", result_meta=None)

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        # Should not raise, but record as no data available
        assert result.guarded is not None
        assert result.guarded["row_cap_gate"]["status"] == "no_result_meta"
        assert result.guarded["row_cap_gate"]["max_rows"] == 100

    @pytest.mark.unit
    def test_result_meta_empty_dict(self):
        """Edge case: result_meta is empty dict."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={},  # Empty, no row_count
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        # Should not raise, but record as no row count available
        assert result.guarded["row_cap_gate"]["status"] == "no_row_count_available"
        assert result.guarded["row_cap_gate"]["max_rows"] == 100

    @pytest.mark.unit
    def test_row_count_is_none(self):
        """Edge case: row_count in result_meta is None."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": None},
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        # Should not raise, but record as no row count available
        assert result.guarded["row_cap_gate"]["status"] == "no_row_count_available"

    @pytest.mark.unit
    def test_row_count_zero(self):
        """Edge case: zero rows returned."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 0},
            assumptions=[],
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        # Should pass and record the zero
        assert result.guarded["row_cap_gate"]["status"] == "within_limit"
        assert result.guarded["row_cap_gate"]["row_count"] == 0
        assert result.assumptions == []

    @pytest.mark.unit
    def test_state_guarded_none_initialized(self):
        """Edge case: state.guarded starts as None, should be initialized."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 50},
            guarded=None,  # Explicitly None
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        # guarded dict should be created
        assert result.guarded is not None
        assert "row_cap_gate" in result.guarded

    @pytest.mark.unit
    def test_state_guarded_preserves_existing_entries(self):
        """Edge case: state.guarded has existing data, should be preserved."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 50},
            guarded={"some_other_gate": {"status": "passed"}},
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        # Previous entries should be preserved
        assert result.guarded["some_other_gate"]["status"] == "passed"
        assert result.guarded["row_cap_gate"]["status"] == "within_limit"

    @pytest.mark.unit
    def test_large_row_count(self):
        """Edge case: very large row count values."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 1_000_000_000},  # 1 billion
            assumptions=[],
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 1_000_000_000}))

        # Should handle large numbers without overflow
        assert result.guarded["row_cap_gate"]["status"] == "within_limit"
        assert result.guarded["row_cap_gate"]["row_count"] == 1_000_000_000

    @pytest.mark.unit
    def test_large_row_count_exceeds_limit(self):
        """Edge case: very large row count exceeds limit."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 1_000_000_001},  # 1 billion + 1
        )

        with pytest.raises(Unsafe):
            asyncio.run(row_cap_gate(state, config={"max_rows": 1_000_000_000}))

    @pytest.mark.unit
    def test_result_meta_with_other_keys(self):
        """Edge case: result_meta contains other metadata besides row_count."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={
                "row_count": 50,
                "execution_time_ms": 123.45,
                "query_hash": "abc123",
                "table_name": "my_table",
            },
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        # Should work correctly and preserve other metadata
        assert result.result_meta["execution_time_ms"] == 123.45
        assert result.result_meta["query_hash"] == "abc123"
        assert result.guarded["row_cap_gate"]["status"] == "within_limit"

    @pytest.mark.unit
    def test_assumptions_list_untouched_when_within_limit(self):
        """Edge case: assumptions list already has other items; a
        within-limit pass adds nothing to it."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 50},
            assumptions=[
                "Assumption 1",
                "Assumption 2",
                "Some other constraint",
            ],
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        assert len(result.assumptions) == 3
        assert "Assumption 1" in result.assumptions
        assert "Assumption 2" in result.assumptions

    @pytest.mark.unit
    def test_boundary_max_rows_zero(self):
        """Edge case: max_rows is 0."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 0},
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 0}))

        # Zero rows should be within limit of 0
        assert result.guarded["row_cap_gate"]["status"] == "within_limit"

    @pytest.mark.unit
    def test_boundary_max_rows_zero_with_one_row(self):
        """Edge case: max_rows is 0 but got 1 row."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 1},
        )

        with pytest.raises(Unsafe):
            asyncio.run(row_cap_gate(state, config={"max_rows": 0}))

    @pytest.mark.unit
    def test_negative_row_count(self):
        """Edge case: row_count is somehow negative (malformed data)."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": -5},
            assumptions=[],
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        # Should pass (negative is less than limit), though unusual
        assert result.guarded["row_cap_gate"]["status"] == "within_limit"
        assert result.guarded["row_cap_gate"]["row_count"] == -5

    @pytest.mark.unit
    def test_negative_max_rows(self):
        """Edge case: max_rows configured as negative (malformed config)."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 50},
        )

        with pytest.raises(Unsafe):
            # Any positive row count exceeds negative max_rows
            asyncio.run(row_cap_gate(state, config={"max_rows": -100}))


class TestRowCapGateIntegration:
    """Integration tests with realistic scenarios."""

    @pytest.mark.unit
    def test_typical_query_scenario(self):
        """Integration: typical query workflow with row cap."""
        # Simulate a query that returned results
        state = OmniState(
            thread_id="conversation_123",
            dataset_id="analytics_db",
            executed_sql="SELECT * FROM sales WHERE year = 2024",
            result_meta={
                "row_count": 456,
                "execution_time_ms": 234.5,
                "columns": ["id", "amount", "date"],
            },
            assumptions=[
                "Only 2024 data included",
            ],
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 1000}))

        assert result.guarded["row_cap_gate"]["status"] == "within_limit"
        assert result.assumptions == ["Only 2024 data included"]

    @pytest.mark.unit
    def test_multiple_gates_scenario(self):
        """Integration: state with data from multiple gates."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 150},
            guarded={
                "sql_allowlist_gate": {"status": "approved"},
                "timeout_gate": {"elapsed_ms": 45},
            },
            assumptions=["SQL is safe"],
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 200}))

        # All previous gate data preserved
        assert result.guarded["sql_allowlist_gate"]["status"] == "approved"
        assert result.guarded["timeout_gate"]["elapsed_ms"] == 45
        assert result.assumptions == ["SQL is safe"]


class TestRowCapGateDataTypes:
    """Test handling of different data types and malformed inputs."""

    @pytest.mark.unit
    def test_row_count_as_float(self):
        """Test row_count provided as float instead of int."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 50.0},  # float instead of int
            assumptions=[],
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        # Should handle float gracefully
        assert result.guarded["row_cap_gate"]["status"] == "within_limit"
        assert result.guarded["row_cap_gate"]["row_count"] == 50.0

    @pytest.mark.unit
    def test_row_count_as_string_in_result_meta(self):
        """Test row_count provided as string in result_meta."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": "50"},  # string instead of int
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        # Comparison with string might behave differently than expected
        # This tests actual behavior
        assert result.guarded["row_cap_gate"]["status"] == "within_limit"

    @pytest.mark.unit
    def test_row_count_as_unparseable_string_in_result_meta(self):
        """Test row_count that can't be coerced to a number at all."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": "not_a_number"},
        )

        result = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))

        assert result.guarded["row_cap_gate"]["status"] == "no_row_count_available"

    @pytest.mark.unit
    def test_multiple_calls_same_state(self):
        """Test calling gate multiple times on same state."""
        state = OmniState(
            thread_id="test_thread",
            result_meta={"row_count": 50},
            assumptions=[],
        )

        # First call
        result1 = asyncio.run(row_cap_gate(state, config={"max_rows": 100}))
        assert result1.assumptions == []

        # Second call with same state (simulate re-running gate)
        result2 = asyncio.run(row_cap_gate(result1, config={"max_rows": 100}))
        assert result2.assumptions == []
