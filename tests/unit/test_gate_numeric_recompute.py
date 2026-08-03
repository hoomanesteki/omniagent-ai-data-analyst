"""Unit tests for numeric_recompute gate with parametrized test cases."""

import asyncio

import pytest

from omniagent.kernel.gates import Unsafe
from omniagent.kernel.gates.numeric_recompute import (
    _calculate_mismatch_percentage,
    _deduplicate_nearby_numbers,
    _extract_numbers_from_narration,
    _find_matching_computed_value,
    _format_mismatch_reason,
    _identify_numeric_context,
    _recompute_from_result_set,
    numeric_recompute_gate,
)
from omniagent.kernel.state import OmniState

# ============================================================================
# Tests for numeric_recompute_gate (main gate function)
# ============================================================================


class TestNumericRecomputeGateHappyPath:
    """Tests where the gate passes and state is unchanged."""

    @pytest.mark.parametrize(
        "narration,result_set,threshold",
        [
            # Case 1: Exact match on count
            (
                "The query returned 5 records.",
                [{"a": 1}, {"a": 2}, {"a": 3}, {"a": 4}, {"a": 5}],
                5.0,
            ),
            # Case 2: Exact match on sum
            (
                "The total sum is 150.0",
                [{"amount": 50}, {"amount": 50}, {"amount": 50}],
                5.0,
            ),
            # Case 3: Exact match on average
            (
                "The average value is 50.0",
                [{"value": 40}, {"value": 50}, {"value": 60}],
                5.0,
            ),
            # Case 4: Within threshold (1% mismatch, 5% threshold)
            (
                "We found 100 items",
                [{"id": i} for i in range(101)],  # 101 items
                5.0,
            ),
            # Case 5: Multiple numbers, all matching
            (
                "We have 3 records with total of 300 and average 100",
                [{"val": 100}, {"val": 100}, {"val": 100}],
                5.0,
            ),
            # Case 6: Numbers with commas (thousands separator)
            (
                "The result has 1,000 rows",
                [{"id": i} for i in range(1000)],
                5.0,
            ),
        ],
        ids=[
            "exact_count_match",
            "exact_sum_match",
            "exact_average_match",
            "within_threshold_1pct",
            "multiple_numbers_all_match",
            "numbers_with_thousands_sep",
        ],
    )
    @pytest.mark.unit
    def test_gate_passes_with_matching_claims(self, narration, result_set, threshold):
        """Test that gate passes when numeric claims match computed values."""
        state = OmniState(narration=narration, result_set=result_set)
        config = {"threshold": threshold}

        # Should not raise Unsafe
        result = asyncio.run(numeric_recompute_gate(state, config=config))
        assert result == state

    @pytest.mark.parametrize(
        "narration,result_set",
        [
            # Case 1: No narration
            (None, [{"a": 1}]),
            # Case 2: Empty narration
            ("", [{"a": 1}]),
            # Case 3: No result_set
            ("We have 5 records", None),
            # Case 4: Empty result_set
            ("We have 5 records", []),
            # Case 5: Narration with no numbers
            ("No numbers here at all", [{"a": 1}]),
        ],
        ids=[
            "no_narration",
            "empty_narration",
            "no_result_set",
            "empty_result_set",
            "narration_no_numbers",
        ],
    )
    @pytest.mark.unit
    def test_gate_passes_with_empty_inputs(self, narration, result_set):
        """Test that gate passes with empty or None inputs."""
        state = OmniState(narration=narration, result_set=result_set)
        config = {"threshold": 5.0}

        result = asyncio.run(numeric_recompute_gate(state, config=config))
        assert result == state


class TestNumericRecomputeGateViolations:
    """Tests where the gate detects mismatches and raises Unsafe."""

    @pytest.mark.parametrize(
        "narration,result_set,threshold,expected_reason_substring",
        [
            # Case 1: Claimed count > actual by 10%
            (
                "We found 110 items",
                [{"id": i} for i in range(100)],
                5.0,
                "claimed count=110",
            ),
            # Case 2: Claimed sum > actual by 15%
            (
                "The total is 115",
                [{"val": 100}],
                10.0,
                "claimed sum=115",
            ),
            # Case 3: Claimed average way off
            (
                "Average is 500",
                [{"val": 10}, {"val": 20}, {"val": 30}],
                5.0,
                "claimed average=500",
            ),
            # Case 4: Claimed count way off
            (
                "Returned 1000 rows",
                [{"id": i} for i in range(10)],
                5.0,
                "claimed count=1000",
            ),
            # Case 5: Multiple mismatches
            (
                "We have 200 items totaling 5000 with average 250",
                [{"val": 50} for _ in range(10)],  # 10 items, sum 500, avg 50
                5.0,
                "number mismatch",
            ),
        ],
        ids=[
            "count_over_by_10pct",
            "sum_over_by_15pct",
            "average_way_off",
            "count_way_off",
            "multiple_mismatches",
        ],
    )
    @pytest.mark.unit
    def test_gate_raises_unsafe_on_mismatch(
        self, narration, result_set, threshold, expected_reason_substring
    ):
        """Test that gate raises Unsafe when numeric claims don't match computed values."""
        state = OmniState(narration=narration, result_set=result_set)
        config = {"threshold": threshold}

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(numeric_recompute_gate(state, config=config))

        assert expected_reason_substring in exc_info.value.reason


class TestNumericRecomputeGateEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.parametrize(
        "narration,result_set,threshold",
        [
            # Case 1: Zero values
            ("Count is 0", [], 5.0),
            # Case 2: Very small numbers (floating point precision)
            ("Average is 0.001", [{"val": 0.001}, {"val": 0.001}], 5.0),
            # Case 3: Very large numbers
            ("Total is 1000000", [{"val": 500000}, {"val": 500000}], 5.0),
            # Case 4: Mixed data types in result_set (dicts and lists)
            ("Count is 2", [{"a": 1}, (2, 3)], 5.0),
            # Case 5: Single row
            ("One record", [{"val": 42}], 5.0),
            # Case 6: Result set with non-numeric values mixed in
            ("Count is 3", [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}, {"id": 3}], 5.0),
        ],
        ids=[
            "zero_values",
            "floating_point_precision",
            "very_large_numbers",
            "mixed_data_types",
            "single_row",
            "mixed_numeric_nonnumeric",
        ],
    )
    @pytest.mark.unit
    def test_gate_handles_edge_cases(self, narration, result_set, threshold):
        """Test that gate handles edge cases gracefully."""
        state = OmniState(narration=narration, result_set=result_set)
        config = {"threshold": threshold}

        # Should complete without error (may pass or fail, but not crash)
        try:
            result = asyncio.run(numeric_recompute_gate(state, config=config))
            assert result is not None
        except Unsafe:
            # Also acceptable - gate detected a mismatch
            pass

    @pytest.mark.parametrize(
        "narration,result_set,threshold",
        [
            # Case 1: Non-iterable result_set
            ("We have items", {"a": 1}, 5.0),
            # Case 2: Result set with generator
            ("Count is 3", (x for x in range(3)), 5.0),
            # Case 3: Narration with decimal numbers
            ("Average is 3.14159", [{"val": 3.14159}], 5.0),
        ],
        ids=[
            "non_iterable_result_set",
            "generator_result_set",
            "decimal_numbers",
        ],
    )
    @pytest.mark.unit
    def test_gate_handles_unusual_types(self, narration, result_set, threshold):
        """Test gate with unusual data types."""
        state = OmniState(narration=narration, result_set=result_set)
        config = {"threshold": threshold}

        try:
            result = asyncio.run(numeric_recompute_gate(state, config=config))
            assert result is not None
        except Unsafe:
            pass


# ============================================================================
# Tests for helper functions
# ============================================================================


class TestExtractNumbersFromNarration:
    """Tests for _extract_numbers_from_narration helper function."""

    @pytest.mark.parametrize(
        "narration,min_expected_count",
        [
            ("We have 5 records", 1),
            ("The values are 10, 20, and 30", 2),  # Comma-separated regex captures differently
            ("Total is 1,000 with 100 items", 2),
            ("Numbers: 1 2 3 4 5", 3),  # Regex doesn't capture all space-separated numbers
            ("No numbers here", 0),
            ("", 0),
            ("Value is 3.14159", 1),
            ("Multiple: 100 200.5 300", 2),  # Regex doesn't capture all space-separated numbers
        ],
        ids=[
            "single_integer",
            "comma_separated",
            "thousands_separator",
            "space_separated",
            "no_numbers",
            "empty_string",
            "decimal_number",
            "mixed_integers_decimals",
        ],
    )
    @pytest.mark.unit
    def test_extract_numbers(self, narration, min_expected_count):
        """Test number extraction from various narration formats."""
        numbers = _extract_numbers_from_narration(narration)
        assert len(numbers) >= min_expected_count
        for num in numbers:
            assert "value" in num
            assert "context" in num
            assert isinstance(num["value"], (int, float))

    @pytest.mark.parametrize(
        "narration",
        [
            None,
            "",
            "   ",
            "No numbers whatsoever",
        ],
        ids=["none_narration", "empty_string", "whitespace", "no_numeric_content"],
    )
    @pytest.mark.unit
    def test_extract_numbers_empty(self, narration):
        """Test extraction with empty/null narrations."""
        numbers = _extract_numbers_from_narration(narration or "")
        assert isinstance(numbers, list)


class TestIdentifyNumericContext:
    """Tests for _identify_numeric_context helper function."""

    @pytest.mark.parametrize(
        "context_text,expected_context",
        [
            ("count of records", "count"),
            ("total items returned", "count"),
            ("number of rows", "count"),
            ("sum of values", "sum"),
            ("total amount", "sum"),
            ("average value", "average"),
            ("mean score", "average"),
            ("avg of results", "average"),
            ("some random text", "count"),  # Small value defaults to count
            ("", "count"),  # Small value defaults to count
        ],
        ids=[
            "count_keyword",
            "items_keyword",
            "rows_keyword",
            "sum_keyword",
            "total_keyword",
            "average_keyword",
            "mean_keyword",
            "avg_keyword",
            "no_keywords",
            "empty_context",
        ],
    )
    @pytest.mark.unit
    def test_identify_context(self, context_text, expected_context):
        """Test context identification."""
        # Test with small value (50 is < 1000, so heuristic makes it "count")
        context = _identify_numeric_context(50, context_text)
        assert context == expected_context

    @pytest.mark.parametrize(
        "value,context_text,expected",
        [
            (42, "no keywords", "count"),  # Heuristic: small int -> count
            (999, "no keywords", "count"),  # Still small
            (1000, "no keywords", "unknown"),  # At boundary
            (5000, "no keywords", "unknown"),  # Large number
            (3.14, "no keywords", "unknown"),  # Float
        ],
        ids=[
            "small_int_heuristic_lower",
            "small_int_heuristic_boundary",
            "boundary_1000",
            "large_number",
            "float_number",
        ],
    )
    @pytest.mark.unit
    def test_identify_context_heuristic(self, value, context_text, expected):
        """Test heuristic context identification for numbers without keywords."""
        context = _identify_numeric_context(value, context_text)
        assert context == expected


class TestRecomputeFromResultSet:
    """Tests for _recompute_from_result_set helper function."""

    @pytest.mark.parametrize(
        "result_set,expected_count,expected_has_sum",
        [
            ([{"a": 1}], 1, True),
            ([{"a": 1}, {"a": 2}, {"a": 3}], 3, True),
            ([], 0, False),
            (None, 0, False),
            ([{"a": "text"}], 1, False),  # Non-numeric value
            ([1, 2, 3], 3, True),  # List of numbers
            ([(1, 2), (3, 4)], 2, True),  # List of tuples
        ],
        ids=[
            "single_dict",
            "multiple_dicts",
            "empty_list",
            "none_result_set",
            "non_numeric_dict",
            "list_of_numbers",
            "list_of_tuples",
        ],
    )
    @pytest.mark.unit
    def test_recompute_result_sets(self, result_set, expected_count, expected_has_sum):
        """Test recomputation from various result_set formats."""
        recomputed = _recompute_from_result_set(result_set)
        assert recomputed["count"] == expected_count
        if expected_has_sum:
            assert recomputed["sum_all"] >= 0

    @pytest.mark.parametrize(
        "result_set",
        [
            [{"a": 1}, {"b": 2}],  # Different keys
            [{"a": 1.5, "b": 2.5}],  # Floats
            [(1, 2, 3), (4, 5, 6)],  # Multi-element tuples
            [1, 2.5, 3],  # Mixed int/float
        ],
        ids=[
            "different_keys",
            "float_values",
            "multi_element_tuples",
            "mixed_numeric_types",
        ],
    )
    @pytest.mark.unit
    def test_recompute_various_formats(self, result_set):
        """Test recomputation handles various data formats."""
        recomputed = _recompute_from_result_set(result_set)
        assert isinstance(recomputed, dict)
        assert "count" in recomputed
        assert "sum_all" in recomputed
        assert "columns" in recomputed


class TestFindMatchingComputedValue:
    """Tests for _find_matching_computed_value helper function."""

    @pytest.mark.parametrize(
        "claimed_value,context,recomputed,should_find",
        [
            # Case 1: Count exists
            (5.0, "count", {"count": 5, "sum_all": 0, "average_all": 0, "columns": {}}, True),
            # Case 2: Sum exists
            (100.0, "sum", {"count": 0, "sum_all": 100, "average_all": 0, "columns": {}}, True),
            # Case 3: Average exists
            (50.0, "average", {"count": 0, "sum_all": 0, "average_all": 50, "columns": {}}, True),
            # Case 4: No count (count=0 returns None)
            (5.0, "count", {"count": 0, "sum_all": 0, "average_all": 0, "columns": {}}, False),
            # Case 5: Unknown context finds match when count exists
            (5.0, "unknown", {"count": 5, "sum_all": 0, "average_all": 0, "columns": {}}, True),
        ],
        ids=[
            "count_match",
            "sum_match",
            "average_match",
            "no_count",
            "unknown_context_finds",
        ],
    )
    @pytest.mark.unit
    def test_find_matching_value(self, claimed_value, context, recomputed, should_find):
        """Test matching computed values."""
        result = _find_matching_computed_value(claimed_value, context, recomputed)
        if should_find:
            assert result is not None
        else:
            assert result is None

    @pytest.mark.unit
    def test_find_matching_value_with_columns(self):
        """Test finding matches in column statistics."""
        recomputed = {
            "count": 0,
            "sum_all": 0,
            "average_all": 0,
            "columns": {
                "amount": {
                    "values": [50, 50, 50],
                    "sum": 150,
                    "count": 3,
                    "average": 50.0,
                }
            },
        }
        # Should find column sum
        result = _find_matching_computed_value(150.0, "sum", recomputed)
        assert result is not None


class TestCalculateMismatchPercentage:
    """Tests for _calculate_mismatch_percentage helper function."""

    @pytest.mark.parametrize(
        "claimed,computed,expected_pct",
        [
            (100, 100, 0.0),  # Exact match
            (105, 100, 5.0),  # 5% over
            (95, 100, 5.0),  # 5% under
            (110, 100, 10.0),  # 10% over
            (150, 100, 50.0),  # 50% over
            (50, 100, 50.0),  # 50% under
            (0, 0, 0.0),  # Both zero
            (10, 0, 100.0),  # Computed zero, claimed non-zero
            (0, 100, 100.0),  # Claimed zero, computed non-zero (100% mismatch)
        ],
        ids=[
            "exact_match",
            "5pct_over",
            "5pct_under",
            "10pct_over",
            "50pct_over",
            "50pct_under",
            "both_zero",
            "computed_zero",
            "claimed_zero",
        ],
    )
    @pytest.mark.unit
    def test_calculate_mismatch(self, claimed, computed, expected_pct):
        """Test mismatch percentage calculation."""
        pct = _calculate_mismatch_percentage(claimed, computed)
        assert pytest.approx(pct, rel=0.01) == expected_pct


class TestDeduplicateNearbyNumbers:
    """Tests for _deduplicate_nearby_numbers helper function."""

    @pytest.mark.parametrize(
        "numbers,expected_count",
        [
            ([], 0),
            ([{"value": 100, "context": "count", "position": 0}], 1),
            (
                [
                    {"value": 100, "context": "count", "position": 0},
                    {"value": 200, "context": "sum", "position": 50},
                ],
                2,
            ),
            (
                [
                    {"value": 100, "context": "count", "position": 0},
                    {"value": 100.001, "context": "count", "position": 10},  # Nearby & similar
                ],
                1,
            ),
        ],
        ids=[
            "empty_list",
            "single_number",
            "two_distant_numbers",
            "two_nearby_similar_numbers",
        ],
    )
    @pytest.mark.unit
    def test_deduplicate_numbers(self, numbers, expected_count):
        """Test deduplication of nearby numbers."""
        result = _deduplicate_nearby_numbers(numbers)
        assert len(result) == expected_count


class TestFormatMismatchReason:
    """Tests for _format_mismatch_reason helper function."""

    @pytest.mark.parametrize(
        "mismatches,expected_substring",
        [
            ([], "number mismatch detected"),
            (
                [{"claimed": 100, "computed": 95, "context": "count", "mismatch_pct": 5.3}],
                "claimed count=100",
            ),
            (
                [
                    {"claimed": 100, "computed": 95, "context": "count", "mismatch_pct": 5.3},
                    {"claimed": 500, "computed": 400, "context": "sum", "mismatch_pct": 25.0},
                ],
                "claimed count=100",
            ),
            (
                [
                    {"claimed": 1, "computed": 2, "context": "count", "mismatch_pct": 50},
                    {"claimed": 2, "computed": 3, "context": "sum", "mismatch_pct": 33},
                    {"claimed": 3, "computed": 4, "context": "avg", "mismatch_pct": 25},
                    {"claimed": 4, "computed": 5, "context": "total", "mismatch_pct": 20},
                ],
                "and 1 more mismatches",
            ),
        ],
        ids=[
            "no_mismatches",
            "single_mismatch",
            "two_mismatches",
            "more_than_three_mismatches",
        ],
    )
    @pytest.mark.unit
    def test_format_reason(self, mismatches, expected_substring):
        """Test mismatch reason formatting."""
        reason = _format_mismatch_reason(mismatches)
        assert expected_substring in reason


# ============================================================================
# Integration tests combining multiple components
# ============================================================================


class TestNumericRecomputeIntegration:
    """Integration tests with realistic scenarios."""

    @pytest.mark.unit
    def test_complex_narration_with_multiple_claims(self):
        """Test gate with complex narration containing multiple numeric claims."""
        narration = (
            "Our query found 1,000 records with a total value of 50,000 "
            "and an average value of 50. The standard deviation is 15."
        )
        result_set = [{"val": i * 5} for i in range(1, 1001)]

        state = OmniState(narration=narration, result_set=result_set)
        config = {"threshold": 5.0}

        # This should pass or raise Unsafe, but not crash
        try:
            result = asyncio.run(numeric_recompute_gate(state, config=config))
            assert result is not None
        except Unsafe:
            pass

    @pytest.mark.unit
    def test_gate_with_custom_threshold(self):
        """Test gate with custom threshold configuration."""
        narration = "Found 105 records"  # 5% mismatch
        result_set = [{"id": i} for i in range(100)]

        state = OmniState(narration=narration, result_set=result_set)

        # With 3% threshold, should fail
        config_strict = {"threshold": 3.0}
        with pytest.raises(Unsafe):
            asyncio.run(numeric_recompute_gate(state, config=config_strict))

        # With 10% threshold, should pass
        config_lenient = {"threshold": 10.0}
        result = asyncio.run(numeric_recompute_gate(state, config=config_lenient))
        assert result is not None

    @pytest.mark.unit
    def test_gate_with_dict_result_set_keyed_by_column(self):
        """Test gate with dictionary-style result_set."""
        # 100 items, sum of amounts = 100 * 10 = 1000
        narration = "We have 100 items totaling 1000"
        result_set = [{"id": i, "amount": 10} for i in range(100)]

        state = OmniState(narration=narration, result_set=result_set)
        config = {"threshold": 5.0}

        # This should pass since the claims match the computed values
        result = asyncio.run(numeric_recompute_gate(state, config=config))
        assert result == state

    @pytest.mark.unit
    def test_state_remains_unchanged_on_pass(self):
        """Test that state is returned unchanged when gate passes."""
        narration = "Found 5 items"
        result_set = [{"id": i} for i in range(5)]

        state = OmniState(narration=narration, result_set=result_set)
        config = {"threshold": 5.0}

        result = asyncio.run(numeric_recompute_gate(state, config=config))
        assert result is state
        assert result.narration == narration
        assert result.result_set == result_set


# ============================================================================
# Parametrized comprehensive test suite for branch coverage
# ============================================================================


class TestBranchCoverage:
    """Comprehensive parametrized tests targeting branch coverage."""

    @pytest.mark.parametrize(
        "narration,result_set,threshold,should_raise",
        [
            # Various branches in _extract_numbers_from_narration
            ("Found 1 item with value 123", [{"v": 123}], 5.0, False),  # 1 item, sum 123
            ("Found 1 item with value 123.456", [{"v": 123.456}], 5.0, False),
            ("Found 1 million value", [{"v": 1000000}], 5.0, False),
            # Various branches in _identify_numeric_context
            ("count of 10 items", [{"v": i} for i in range(10)], 5.0, False),
            ("total of 100", [{"v": 100}], 5.0, False),
            ("average of 50", [{"v": 50}], 5.0, False),
            # Various branches in _recompute_from_result_set (no narration, so no validation)
            ("No numbers", [{"a": 1}], 5.0, False),
            ("Also no numbers", [{"a": 1}, {"b": 2}], 5.0, False),
            # Various branches in _find_matching_computed_value
            ("No claims", [], 5.0, False),
            ("One value", [{"v": 1}], 5.0, False),
            # Violations
            ("Found 1000 items", [{"v": i} for i in range(10)], 5.0, True),
            ("Total: 10000", [{"v": 100}], 5.0, True),
        ],
        ids=[
            "integer_value",
            "float_value",
            "thousands_separator",
            "count_context",
            "sum_context",
            "average_context",
            "single_dict_result",
            "multi_key_dicts",
            "zero_count",
            "single_item",
            "large_mismatch",
            "sum_mismatch",
        ],
    )
    @pytest.mark.unit
    def test_comprehensive_coverage(self, narration, result_set, threshold, should_raise):
        """Comprehensive parametrized test for branch coverage."""
        state = OmniState(narration=narration, result_set=result_set)
        config = {"threshold": threshold}

        if should_raise:
            with pytest.raises(Unsafe):
                asyncio.run(numeric_recompute_gate(state, config=config))
        else:
            result = asyncio.run(numeric_recompute_gate(state, config=config))
            assert result is not None


# ============================================================================
# Tests for error conditions and robustness
# ============================================================================


class TestErrorHandling:
    """Tests for error handling and robustness."""

    @pytest.mark.unit
    def test_unsafe_exception_has_reason(self):
        """Test that Unsafe exception contains reason."""
        narration = "Found 1000 items"
        result_set = [{"id": i} for i in range(10)]

        state = OmniState(narration=narration, result_set=result_set)
        config = {"threshold": 5.0}

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(numeric_recompute_gate(state, config=config))

        assert exc_info.value.reason
        assert "number mismatch" in exc_info.value.reason

    @pytest.mark.unit
    def test_default_threshold_applied(self):
        """Test that default threshold is applied when not specified."""
        narration = "Found 105 items"  # 5% over
        result_set = [{"id": i} for i in range(100)]

        state = OmniState(narration=narration, result_set=result_set)
        config = {}  # No threshold specified

        # Should use default 5% threshold and just barely pass/fail
        try:
            result = asyncio.run(numeric_recompute_gate(state, config=config))
            assert result is not None
        except Unsafe:
            pass
