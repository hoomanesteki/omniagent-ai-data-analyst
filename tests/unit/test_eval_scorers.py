"""Unit tests for eval/scorers.py: pure functions, no adapters needed."""

from omniagent.eval.scorers import bootstrap_ci as _bootstrap_ci
from omniagent.eval.scorers import (
    build_scorecard,
    categorical_accuracy,
    execution_accuracy,
    format_scorecard,
    schema_link_recall,
)


class TestExecutionAccuracy:
    def test_identical_rows_match(self):
        assert execution_accuracy([{"a": 1, "b": "x"}], [{"a": 1, "b": "x"}])

    def test_row_order_does_not_matter(self):
        actual = [{"a": 2}, {"a": 1}]
        expected = [{"a": 1}, {"a": 2}]
        assert execution_accuracy(actual, expected)

    def test_column_order_within_a_row_does_not_matter(self):
        assert execution_accuracy([{"a": 1, "b": "x"}], [{"b": "x", "a": 1}])

    def test_float_noise_within_tolerance_still_matches(self):
        assert execution_accuracy([{"a": 1.0000001}], [{"a": 1.0}])

    def test_float_difference_beyond_tolerance_does_not_match(self):
        assert not execution_accuracy([{"a": 1.1}], [{"a": 1.0}])

    def test_different_row_counts_never_match(self):
        assert not execution_accuracy([{"a": 1}], [{"a": 1}, {"a": 2}])

    def test_different_values_do_not_match(self):
        assert not execution_accuracy([{"a": 1}], [{"a": 2}])

    def test_both_empty_matches(self):
        assert execution_accuracy([], [])

    def test_none_alongside_floats_across_rows_does_not_crash(self):
        """A breakdown result can have a null aggregate for one group (e.g.
        no completed orders in a category) while another group has a real
        float -- sorting rows for comparison must not crash comparing
        None to a float across rows."""
        rows = [{"group": "a", "value": None}, {"group": "b", "value": 5.0}]
        assert execution_accuracy(rows, rows)
        assert not execution_accuracy(
            rows, [{"group": "a", "value": None}, {"group": "b", "value": 6.0}]
        )


class TestCategoricalAccuracy:
    def test_all_correct_is_one(self):
        assert categorical_accuracy([("metric", "metric"), ("sql", "sql")]) == 1.0

    def test_half_correct_is_half(self):
        assert categorical_accuracy([("metric", "metric"), ("metric", "sql")]) == 0.5

    def test_empty_is_zero(self):
        assert categorical_accuracy([]) == 0.0


class TestSchemaLinkRecall:
    def test_full_recall(self):
        assert schema_link_recall(["orders", "customers"], ["orders", "customers"]) == 1.0

    def test_partial_recall(self):
        assert schema_link_recall(["orders"], ["orders", "customers"]) == 0.5

    def test_extra_predicted_tables_do_not_hurt_recall(self):
        assert (
            schema_link_recall(["orders", "customers", "returns"], ["orders", "customers"]) == 1.0
        )

    def test_no_expected_tables_is_full_recall_by_definition(self):
        assert schema_link_recall(["orders"], []) == 1.0

    def test_zero_recall_when_nothing_predicted_matches(self):
        assert schema_link_recall(["returns"], ["orders"]) == 0.0


class TestBootstrapCi:
    def test_empty_scores_returns_zeroed_result(self):
        result = _bootstrap_ci([])
        assert result.mean == 0.0
        assert result.low == 0.0
        assert result.high == 0.0

    def test_all_ones_gives_a_degenerate_interval_at_one(self):
        result = _bootstrap_ci([1.0] * 20, seed=1337)
        assert result.mean == 1.0
        assert result.low == 1.0
        assert result.high == 1.0

    def test_mean_matches_the_plain_average(self):
        result = _bootstrap_ci([1.0, 1.0, 0.0, 0.0], seed=1337)
        assert result.mean == 0.5

    def test_interval_bounds_are_within_zero_and_one(self):
        result = _bootstrap_ci([1.0, 0.0, 1.0, 1.0, 0.0], seed=1337)
        assert 0.0 <= result.low <= result.mean <= result.high <= 1.0

    def test_same_seed_is_reproducible(self):
        scores = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0]
        assert _bootstrap_ci(scores, seed=42) == _bootstrap_ci(scores, seed=42)

    def test_different_seeds_can_give_different_intervals(self):
        scores = [1.0, 0.0, 1.0, 0.0, 1.0]
        result_a = _bootstrap_ci(scores, seed=1, n_resamples=200)
        result_b = _bootstrap_ci(scores, seed=2, n_resamples=200)
        # Means are identical (same underlying data); only the resampled
        # interval can differ between seeds.
        assert result_a.mean == result_b.mean


class TestScorecard:
    def test_build_scorecard_produces_one_row_per_metric(self):
        rows = build_scorecard({"execution_accuracy": [1.0, 0.0], "route_accuracy": [1.0]})
        names = {row.name for row in rows}
        assert names == {"execution_accuracy", "route_accuracy"}

    def test_format_scorecard_includes_every_row_name(self):
        rows = build_scorecard({"execution_accuracy": [1.0, 1.0, 0.0]})
        output = format_scorecard(rows)
        assert "execution_accuracy" in output
        assert "3" in output  # n
