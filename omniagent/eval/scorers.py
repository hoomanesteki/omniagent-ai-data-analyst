"""Scorers: execution accuracy, component accuracy, schema-link recall, and
bootstrap confidence intervals over any of them.

No ML here, matching the rest of this project's guardrails: every scorer is
a deterministic comparison. Bootstrap resampling uses Python's own `random`
with a fixed default seed, so a scorecard is reproducible run to run unless
the caller deliberately asks for a different seed.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_DEFAULT_SEED = 1337


def _normalize_row(row: dict[str, Any], *, ndigits: int) -> tuple[tuple[str, Any], ...]:
    normalized = []
    for key in sorted(row.keys()):
        value = row[key]
        if isinstance(value, float):
            value = round(value, ndigits)
        normalized.append((key, value))
    return tuple(normalized)


def execution_accuracy(
    actual: Sequence[dict[str, Any]], expected: Sequence[dict[str, Any]], *, ndigits: int = 6
) -> bool:
    """Row-order-independent, float-tolerant comparison of two result sets.

    Column order within a row and row order within the set both don't
    matter -- what matters is that the same (key, value) pairs are present,
    with floats rounded to `ndigits` so a real query's floating-point noise
    doesn't fail an otherwise-correct answer.
    """
    if len(actual) != len(expected):
        return False
    # key=repr rather than relying on the tuples' own ordering: a row's
    # values can mix None with floats/strings across different rows (e.g. a
    # breakdown with a null-average group), and Python has no `<` between
    # None and a float. repr() is always comparable and preserves a stable
    # order for equality-checking the two sorted sequences afterward.
    actual_rows = sorted((_normalize_row(row, ndigits=ndigits) for row in actual), key=repr)
    expected_rows = sorted((_normalize_row(row, ndigits=ndigits) for row in expected), key=repr)
    return actual_rows == expected_rows


def categorical_accuracy(predictions: Sequence[tuple[Any, Any]]) -> float:
    """Mean exact-match rate over (actual, expected) pairs.

    The same primitive whether it's being used to score route decisions,
    metric-match decisions, or any other categorical prediction -- what
    changes is only what the caller feeds in.
    """
    if not predictions:
        return 0.0
    matches = sum(1 for actual, expected in predictions if actual == expected)
    return matches / len(predictions)


def schema_link_recall(predicted_tables: Sequence[str], expected_tables: Sequence[str]) -> float:
    """Fraction of the tables a query genuinely needed that a generated
    SQL candidate actually referenced. Undefined (returns 1.0) when the
    gold item names no tables, since there is nothing to have missed."""
    expected_set = set(expected_tables)
    if not expected_set:
        return 1.0
    predicted_set = set(predicted_tables)
    return len(predicted_set & expected_set) / len(expected_set)


@dataclass(frozen=True)
class BootstrapResult:
    """A point estimate with a bootstrap confidence interval around it."""

    mean: float
    low: float
    high: float
    confidence: float


def bootstrap_ci(
    scores: Sequence[float],
    *,
    n_resamples: int = 2000,
    confidence: float = 0.95,
    seed: int | None = _DEFAULT_SEED,
) -> BootstrapResult:
    """Percentile bootstrap confidence interval over a list of per-item scores
    (each 0.0/1.0 for a pass/fail metric, or any other per-item float)."""
    if not scores:
        return BootstrapResult(mean=0.0, low=0.0, high=0.0, confidence=confidence)

    rng = random.Random(seed)  # noqa: S311 - statistical resampling, not cryptographic use
    n = len(scores)
    resampled_means = []
    for _ in range(n_resamples):
        resample = [scores[rng.randrange(n)] for _ in range(n)]
        resampled_means.append(sum(resample) / n)
    resampled_means.sort()

    alpha = 1 - confidence
    low_index = max(0, int((alpha / 2) * n_resamples))
    high_index = min(n_resamples - 1, int((1 - alpha / 2) * n_resamples))

    return BootstrapResult(
        mean=sum(scores) / n,
        low=resampled_means[low_index],
        high=resampled_means[high_index],
        confidence=confidence,
    )


@dataclass(frozen=True)
class ScorecardRow:
    """One named metric's result, ready to print."""

    name: str
    result: BootstrapResult
    n: int


def build_scorecard(
    metrics: Mapping[str, Sequence[float]], **bootstrap_kwargs: Any
) -> list[ScorecardRow]:
    """Turn `{metric_name: [per_item_scores]}` into printable scorecard rows,
    each with its own bootstrap confidence interval."""
    return [
        ScorecardRow(name=name, result=bootstrap_ci(scores, **bootstrap_kwargs), n=len(scores))
        for name, scores in metrics.items()
    ]


def format_scorecard(rows: Sequence[ScorecardRow]) -> str:
    lines = [f"{'metric':<28} {'n':>5} {'mean':>8} {'ci_low':>8} {'ci_high':>8}"]
    lines.append("-" * len(lines[0]))
    for row in rows:
        lines.append(
            f"{row.name:<28} {row.n:>5} {row.result.mean:>8.1%} "
            f"{row.result.low:>8.1%} {row.result.high:>8.1%}"
        )
    return "\n".join(lines)
