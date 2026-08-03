"""Unit tests for empty_result_gate: enforce abstention on zero-row results.

This test module covers:
- Happy path: gate passes when result has rows and narration is clean
- Violation: gate raises Unsafe when narration contains numeric values
- Edge cases: empty results, None values, boundary conditions, whitespace handling
"""

import pytest

from omniagent.kernel.gates.empty_result import empty_result_gate
from omniagent.kernel.gates.exceptions import Unsafe
from omniagent.kernel.state import OmniState

pytestmark = pytest.mark.asyncio


class TestEmptyResultGateHappyPath:
    """Happy path tests: gate passes, returns modified state as expected."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "row_count,narration,expected_abstain",
        [
            # Non-empty results pass cleanly
            (5, "Records retrieved successfully.", False),
            (100, "Results retrieved successfully.", False),
            (1, "Single row returned.", False),
            # Empty result triggers abstention
            (0, "No data available.", True),
            (0, None, True),
        ],
    )
    async def test_result_with_various_row_counts(self, row_count, narration, expected_abstain):
        """Test gate response to different row counts with clean narration."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": row_count},
            narration=narration,
        )
        result = await empty_result_gate(state, config={})
        assert result.guarded is not None
        assert result.guarded["empty_result_gate"]["is_empty"] == (row_count == 0)
        assert result.guarded["empty_result_gate"]["row_count"] == row_count
        if expected_abstain:
            assert result.guarded.get("abstain") is True
        else:
            # For non-empty results, abstain should not be set (None)
            assert result.guarded.get("abstain") is None

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "narration",
        [
            "Data successfully retrieved.",
            "Query completed without numeric data.",
            "No results found in the database.",
            "The search returned no matches.",
            "Processing complete.",
            "",  # Empty narration is safe
        ],
    )
    async def test_clean_narration_passes(self, narration):
        """Test that clean narrations (no digits) pass the gate."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 10},
            narration=narration,
        )
        result = await empty_result_gate(state, config={})
        assert result.guarded is not None
        assert result.guarded["empty_result_gate"]["is_empty"] is False
        # Should not raise Unsafe

    @pytest.mark.unit
    async def test_guarded_narration_field_takes_precedence(self):
        """Test that guarded.narration is checked first, then state.narration."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 10},
            narration="safe narration",
        )
        state.guarded = {"narration": "also safe"}
        result = await empty_result_gate(state, config={})
        # Should not raise and should process guarded narration
        assert result.guarded is not None

    @pytest.mark.unit
    async def test_gate_initializes_guarded_dict_if_none(self):
        """Test that gate creates guarded dict if state.guarded is None."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 5},
            narration="safe",
        )
        assert state.guarded is None
        result = await empty_result_gate(state, config={})
        assert result.guarded is not None
        assert isinstance(result.guarded, dict)
        assert "empty_result_gate" in result.guarded


class TestEmptyResultGateViolations:
    """Violation tests: gate raises Unsafe when narration contains numeric values."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "narration",
        [
            "Found 5 results.",  # Simple integer
            "The value is 123.",  # Multi-digit integer
            "Average: 45.67",  # Decimal/float
            "Result: 3.14159",  # Floating point
            "In scientific notation: 1e-5",  # Scientific notation (e- format)
            "Another: 2E+3",  # Scientific notation (E+ format)
            "Mixed: 123.456e-10",  # Complex scientific
            "Started at 2024-01-15, found 42 rows.",  # Mixed: date and number
            "0 results found.",  # Zero is still numeric
            "Query returned 1000000 records.",  # Large integer
            "Precision: 0.00001",  # Small decimal
            "Range 1.0 to 10.5",  # Multiple floats
            "ID: 999, Name: test",  # Embedded numeric
            "The answer is 42.",  # Standalone integer
            "Version 2.5.1 installed.",  # Version-like format with dots
            "123",  # Only number
            "  456  ",  # Whitespace-padded number
            "Records: 7",  # Number with space (word boundary)
        ],
    )
    async def test_narration_with_numeric_values_raises(self, narration):
        """Test that narration containing any numeric value raises Unsafe."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 10},
            narration=narration,
        )
        with pytest.raises(Unsafe) as exc_info:
            await empty_result_gate(state, config={})
        assert "numeric values" in exc_info.value.reason.lower()
        assert "mask empty result" in exc_info.value.reason.lower()

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "narration",
        [
            "Query found data.",
            "Processing complete.",
            "No results available.",
            "Success.",
            "Failed to retrieve data.",
        ],
    )
    async def test_clean_narration_does_not_raise(self, narration):
        """Test that truly clean narrations do not raise Unsafe."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 10},
            narration=narration,
        )
        result = await empty_result_gate(state, config={})
        assert result is not None

    @pytest.mark.unit
    async def test_guarded_narration_with_numeric_raises(self):
        """Test that numeric values in guarded.narration field also raise Unsafe."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 10},
            narration="safe",
        )
        state.guarded = {"narration": "Found 42 items"}
        with pytest.raises(Unsafe):
            await empty_result_gate(state, config={})


class TestEmptyResultGateEdgeCases:
    """Edge case tests: None values, missing fields, boundary conditions."""

    @pytest.mark.unit
    async def test_none_result_meta(self):
        """Test gate with result_meta=None."""
        state = OmniState(
            thread_id="test",
            result_meta=None,
            narration="safe narration",
        )
        result = await empty_result_gate(state, config={})
        assert result.guarded is not None
        assert result.guarded["empty_result_gate"]["has_result_meta"] is False
        assert result.guarded["empty_result_gate"]["is_empty"] is False
        assert result.guarded["empty_result_gate"]["row_count"] is None

    @pytest.mark.unit
    async def test_result_meta_missing_row_count(self):
        """Test gate with result_meta dict but no row_count key."""
        state = OmniState(
            thread_id="test",
            result_meta={"other_field": "value"},
            narration="safe",
        )
        result = await empty_result_gate(state, config={})
        assert result.guarded is not None
        assert result.guarded["empty_result_gate"]["is_empty"] is False
        assert result.guarded["empty_result_gate"]["row_count"] is None

    @pytest.mark.unit
    async def test_result_meta_non_dict(self):
        """Test gate with result_meta as non-dict type."""
        state = OmniState(
            thread_id="test",
            result_meta="not a dict",  # type: ignore
            narration="safe",
        )
        result = await empty_result_gate(state, config={})
        assert result.guarded is not None
        assert result.guarded["empty_result_gate"]["is_empty"] is False
        assert result.guarded["empty_result_gate"]["row_count"] is None

    @pytest.mark.unit
    async def test_result_meta_row_count_non_int(self):
        """Test gate with row_count as non-int type."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": "5"},  # String instead of int
            narration="safe",
        )
        result = await empty_result_gate(state, config={})
        assert result.guarded is not None
        assert result.guarded["empty_result_gate"]["is_empty"] is False
        # row_count in guarded will be the raw value (even if not int)
        assert result.guarded["empty_result_gate"]["row_count"] == "5"

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "row_count,should_abstain",
        [
            (0, True),
            (-1, False),  # Negative count treated as non-zero
            (2147483647, False),  # Large positive integer
        ],
    )
    async def test_row_count_boundary_values(self, row_count, should_abstain):
        """Test gate with boundary row_count values."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": row_count},
            narration="safe",
        )
        result = await empty_result_gate(state, config={})
        assert result.guarded is not None
        assert result.guarded["empty_result_gate"]["is_empty"] == (row_count == 0)
        if should_abstain:
            assert result.guarded.get("abstain") is True
        else:
            assert result.guarded.get("abstain") is None

    @pytest.mark.unit
    async def test_none_narration_with_empty_result(self):
        """Test that None narration with empty result sets abstain flag."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 0},
            narration=None,
        )
        result = await empty_result_gate(state, config={})
        assert result.guarded is not None
        assert result.guarded["empty_result_gate"]["is_empty"] is True
        assert result.guarded["abstain"] is True

    @pytest.mark.unit
    async def test_empty_string_narration_with_rows(self):
        """Test that empty string narration with rows passes."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 5},
            narration="",
        )
        result = await empty_result_gate(state, config={})
        assert result.guarded is not None
        assert result.guarded["empty_result_gate"]["is_empty"] is False

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "narration",
        [
            "   safe with whitespace   ",
            "\n\nclean\n\n",
            "\t\tindented\t\t",
            "safe\x00with\x00null",  # Null characters
        ],
    )
    async def test_narration_with_whitespace_and_special_chars(self, narration):
        """Test narrations with various whitespace and special characters."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 10},
            narration=narration,
        )
        result = await empty_result_gate(state, config={})
        assert result.guarded is not None
        assert result.guarded["empty_result_gate"]["is_empty"] is False

    @pytest.mark.unit
    async def test_narration_non_string_type(self):
        """Test gate when narration is non-string type."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 10},
            narration=None,  # Explicitly None
        )
        result = await empty_result_gate(state, config={})
        # Should not raise or error
        assert result.guarded is not None

    @pytest.mark.unit
    async def test_guarded_narration_non_string_type(self):
        """Test gate when guarded.narration is non-string type."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 10},
            narration="safe",
        )
        state.guarded = {"narration": 123}  # Non-string in guarded
        result = await empty_result_gate(state, config={})
        # Should fall back to checking state.narration
        assert result.guarded is not None


class TestEmptyResultGateAbstainFlag:
    """Test the abstain flag behavior in various scenarios."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "row_count,expected_abstain",
        [
            (0, True),
            (1, False),
            (10, False),
            (100, False),
        ],
    )
    async def test_abstain_flag_set_only_on_empty_result(self, row_count, expected_abstain):
        """Test that abstain flag is only set when result is empty."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": row_count},
            narration="safe",
        )
        result = await empty_result_gate(state, config={})
        if expected_abstain:
            assert result.guarded.get("abstain") is True
        else:
            assert result.guarded.get("abstain") is None

    @pytest.mark.unit
    async def test_abstain_flag_not_overwritten_on_non_empty(self):
        """Test that non-empty results don't clear existing abstain flags."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 5},
            narration="safe",
        )
        state.guarded = {"abstain": True}  # Pre-existing flag
        result = await empty_result_gate(state, config={})
        # Non-empty result should not set abstain, but shouldn't clear it either
        assert result.guarded.get("abstain") is True


class TestEmptyResultGateNumericPatterns:
    """Test numeric pattern detection in narration."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "narration",
        [
            # Integers
            "0",
            "1",
            "999",
            "123456789",
            # Decimals
            "0.1",
            "3.14",
            "999.999",
            "0.0000001",
            # Scientific notation
            "1e5",
            "1e-5",
            "1.5e3",
            "1.5e-3",
            "1E5",
            "1E-5",
            # With context
            "Value is 5",
            "Result: 42",
            "Found 10 items",
            "Count=99",
            "Version 2.1.3",
            "2024",
            "3.14159",
        ],
    )
    async def test_numeric_pattern_detection(self, narration):
        """Test that all numeric patterns are correctly detected."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 10},
            narration=narration,
        )
        with pytest.raises(Unsafe):
            await empty_result_gate(state, config={})

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "narration",
        [
            # Non-numeric patterns that might be confused
            "abc",
            "test",
            "data",
            "no numbers here",
            "single",
            "double",
            "query",
            "result",
            "safe",
        ],
    )
    async def test_non_numeric_patterns_pass(self, narration):
        """Test that non-numeric narrations pass the gate."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 10},
            narration=narration,
        )
        result = await empty_result_gate(state, config={})
        assert result.guarded is not None


class TestEmptyResultGateStateModification:
    """Test that gate correctly modifies and returns state."""

    @pytest.mark.unit
    async def test_gate_returns_same_state_object(self):
        """Test that gate returns the same state object (modified in-place)."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 5},
            narration="safe",
        )
        result = await empty_result_gate(state, config={})
        # Should be the same object
        assert result is state

    @pytest.mark.unit
    async def test_gate_populates_guarded_empty_result_gate_key(self):
        """Test that gate populates guarded['empty_result_gate'] with all fields."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 5},
            narration="safe",
        )
        result = await empty_result_gate(state, config={})
        assert "empty_result_gate" in result.guarded
        gate_info = result.guarded["empty_result_gate"]
        assert "is_empty" in gate_info
        assert "row_count" in gate_info
        assert "has_result_meta" in gate_info

    @pytest.mark.unit
    async def test_gate_preserves_other_guarded_fields(self):
        """Test that gate preserves existing guarded fields."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 5},
            narration="safe",
        )
        state.guarded = {"existing_field": "value"}
        result = await empty_result_gate(state, config={})
        assert result.guarded["existing_field"] == "value"
        assert "empty_result_gate" in result.guarded


class TestEmptyResultGateConfiguration:
    """Test configuration parameter handling."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "config",
        [
            {},  # Empty config
            {"unused_key": "value"},  # Config doesn't affect gate
            {"foo": "bar", "baz": 123},
        ],
    )
    async def test_gate_with_various_configs(self, config):
        """Test that gate handles various config dicts gracefully."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 5},
            narration="safe",
        )
        result = await empty_result_gate(state, config=config)
        assert result.guarded is not None


class TestEmptyResultGateIntegration:
    """Integration-style tests combining multiple gate behaviors."""

    @pytest.mark.unit
    async def test_full_flow_empty_result_with_clean_narration(self):
        """Test complete flow: empty result with safe narration."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 0},
            narration="No matching records found.",
        )
        result = await empty_result_gate(state, config={})
        assert result.guarded["abstain"] is True
        assert result.guarded["empty_result_gate"]["is_empty"] is True

    @pytest.mark.unit
    async def test_full_flow_nonempty_result_with_unsafe_narration(self):
        """Test complete flow: non-empty result but unsafe narration."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 10},
            narration="Found 10 items in the database.",
        )
        with pytest.raises(Unsafe):
            await empty_result_gate(state, config={})

    @pytest.mark.unit
    async def test_full_flow_empty_result_is_detected_even_with_missing_narration(self):
        """Test that empty result is detected even when narration is missing."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 0},
            narration=None,
        )
        result = await empty_result_gate(state, config={})
        assert result.guarded["abstain"] is True
        assert result.guarded["empty_result_gate"]["is_empty"] is True

    @pytest.mark.unit
    async def test_multiple_calls_accumulate_guard_state(self):
        """Test that calling gate multiple times on same state accumulates data."""
        state = OmniState(
            thread_id="test",
            result_meta={"row_count": 5},
            narration="safe",
        )
        result1 = await empty_result_gate(state, config={})
        assert "empty_result_gate" in result1.guarded
        # Call again - should preserve previous state
        result2 = await empty_result_gate(result1, config={})
        assert "empty_result_gate" in result2.guarded
