"""Vendor-neutral metric catalog and deterministic phrase matching.

The catalog is what lets the router skip the model entirely: if a question
names a metric the catalog knows, there is nothing for an LLM to decide. The
matcher is therefore deliberately conservative — it returns a match only when
the evidence is unambiguous, and reports ties rather than guessing between
them.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Tie-break priority when a metric's name, label, and synonyms normalize to
# phrases of identical length — lower wins. Keeps Match.matched_on/score
# deterministic instead of depending on set iteration order.
_KIND_PRIORITY = {"name": 0, "label": 1, "synonym": 2}


def normalize(text: str) -> str:
    """Casefold, strip accents, and collapse punctuation to single spaces."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", stripped.casefold()).split())


@dataclass(frozen=True)
class DisplayFormat:
    """How a metric's value should be rendered."""

    type: str = "number"  # number | currency | percent | duration
    precision: int = 2
    currency: str | None = None
    good_direction: str | None = None  # up | down | None


@dataclass(frozen=True)
class MetricInfo:
    """A metric the semantic layer can answer for."""

    name: str
    label: str
    description: str = ""
    synonyms: tuple[str, ...] = ()
    format: DisplayFormat = field(default_factory=DisplayFormat)
    default_grain: str | None = None


@dataclass(frozen=True)
class DimensionInfo:
    """A dimension a metric can be grouped or filtered by."""

    name: str
    label: str
    type: str  # time | categorical | boolean | numeric
    description: str = ""
    synonyms: tuple[str, ...] = ()
    is_pii: bool = False


@dataclass(frozen=True)
class Match:
    """A deterministic catalog hit."""

    metric: str
    score: float
    matched_on: str  # name | synonym | label
    dimensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Ambiguous:
    """Two or more candidates tied — the caller must clarify, not guess."""

    candidates: tuple[str, ...]
    reason: str


@dataclass
class Catalog:
    """Metrics and dimensions for one dataset, with deterministic matching."""

    dataset_id: str
    metrics: dict[str, MetricInfo] = field(default_factory=dict)
    dimensions: dict[str, DimensionInfo] = field(default_factory=dict)

    def metric_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.metrics))

    def dimension_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.dimensions))

    def pii_dimensions(self) -> tuple[str, ...]:
        return tuple(sorted(n for n, d in self.dimensions.items() if d.is_pii))

    def match(self, question: str) -> Match | Ambiguous | None:
        """Match a question to exactly one metric, or report why it cannot.

        Scoring is by longest matched phrase, so "net revenue" beats "revenue"
        when both are known. A tie between distinct metrics is reported as
        ``Ambiguous`` rather than resolved arbitrarily — guessing here is what
        produces confidently wrong answers.
        """
        text = normalize(question)
        if not text:
            return None

        best: list[tuple[int, str, str]] = []
        for name, metric in self.metrics.items():
            for phrase, kind in self._phrases(name, metric):
                if self._contains_phrase(text, phrase):
                    best.append((len(phrase), name, kind))

        if not best:
            return None

        top_len = max(item[0] for item in best)
        winners = {(name, kind) for length, name, kind in best if length == top_len}
        winning_metrics = {name for name, _ in winners}

        if len(winning_metrics) > 1:
            return Ambiguous(
                candidates=tuple(sorted(winning_metrics)),
                reason="Multiple metrics matched the same phrase length",
            )

        metric_name = winning_metrics.pop()
        # A metric's name and label often normalize to the same phrase (e.g.
        # "net_revenue" / "Net revenue"), tying on length. Break the tie by
        # explicit priority rather than set iteration order, which is
        # per-process hash-randomized and would make `matched_on`/`score`
        # nondeterministic across runs for exactly this common case.
        matching_kinds = [k for n, k in winners if n == metric_name]
        kind = min(matching_kinds, key=_KIND_PRIORITY.__getitem__)
        return Match(
            metric=metric_name,
            score=1.0 if kind == "name" else 0.9,
            matched_on=kind,
            dimensions=self.match_dimensions(question),
        )

    def match_dimensions(self, question: str) -> tuple[str, ...]:
        """Every dimension whose name, label, or synonym appears in the question."""
        text = normalize(question)
        hits: list[tuple[int, str]] = []
        for name, dimension in self.dimensions.items():
            for phrase in self._dimension_phrases(name, dimension):
                if self._contains_phrase(text, phrase):
                    hits.append((len(phrase), name))
                    break
        return tuple(name for _, name in sorted(hits, reverse=True))

    @staticmethod
    def _contains_phrase(haystack: str, needle: str) -> bool:
        """Substring match constrained to whole words."""
        return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None

    @staticmethod
    def _phrases(name: str, metric: MetricInfo) -> list[tuple[str, str]]:
        phrases = [(normalize(name.replace("_", " ")), "name")]
        if metric.label:
            phrases.append((normalize(metric.label), "label"))
        phrases.extend((normalize(s), "synonym") for s in metric.synonyms)
        return [(p, kind) for p, kind in phrases if p]

    @staticmethod
    def _dimension_phrases(name: str, dimension: DimensionInfo) -> list[str]:
        phrases = [normalize(name.replace("_", " ").replace(".", " "))]
        if dimension.label:
            phrases.append(normalize(dimension.label))
        phrases.extend(normalize(s) for s in dimension.synonyms)
        return sorted((p for p in phrases if p), key=len, reverse=True)
