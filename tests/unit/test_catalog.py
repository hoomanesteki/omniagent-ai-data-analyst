"""Unit tests for the vendor-neutral metric catalog and deterministic matching."""

import pytest

from omniagent.kernel.catalog import (
    Ambiguous,
    Catalog,
    DimensionInfo,
    Match,
    MetricInfo,
    normalize,
)


@pytest.fixture
def catalog():
    return Catalog(
        dataset_id="ecommerce",
        metrics={
            "net_revenue": MetricInfo(
                name="net_revenue",
                label="Net revenue",
                synonyms=("net sales", "revenue after refunds"),
            ),
            "gross_revenue": MetricInfo(
                name="gross_revenue",
                label="Gross revenue",
                synonyms=("revenue", "sales"),
            ),
            "order_count": MetricInfo(
                name="order_count",
                label="Orders",
                synonyms=("number of orders",),
            ),
        },
        dimensions={
            "orders.channel": DimensionInfo(
                name="orders.channel",
                label="Channel",
                type="categorical",
                synonyms=("sales channel",),
            ),
            "customers.email": DimensionInfo(
                name="customers.email",
                label="Customer email",
                type="categorical",
                is_pii=True,
            ),
        },
    )


class TestNormalize:
    def test_casefolds_and_strips_punctuation(self):
        assert normalize("Net Revenue?!") == "net revenue"

    def test_strips_accents(self):
        assert normalize("café") == "cafe"

    def test_collapses_whitespace(self):
        assert normalize("net    revenue\n\tby channel") == "net revenue by channel"


class TestCatalogMatch:
    def test_exact_name_match(self, catalog):
        result = catalog.match("net revenue")
        assert isinstance(result, Match)
        assert result.metric == "net_revenue"
        assert result.matched_on == "name"
        assert result.score == 1.0

    def test_label_match(self, catalog):
        """order_count's label 'Orders' differs from its name-normalized
        'order count', so a question containing only the label phrase (not
        the full name or synonym) resolves as a genuine label match."""
        result = catalog.match("how many orders were there")
        assert isinstance(result, Match)
        assert result.metric == "order_count"
        assert result.matched_on == "label"
        assert result.score == 0.9

    def test_name_wins_over_label_when_both_tie_in_length(self, catalog):
        """gross_revenue's name ('gross revenue') and label ('Gross revenue')
        normalize identically and tie in length — name must win
        deterministically rather than depending on set iteration order."""
        result = catalog.match("what's the gross revenue")
        assert isinstance(result, Match)
        assert result.metric == "gross_revenue"
        assert result.matched_on == "name"
        assert result.score == 1.0

    def test_synonym_match(self, catalog):
        result = catalog.match("number of orders please")
        assert isinstance(result, Match)
        assert result.metric == "order_count"
        assert result.matched_on == "synonym"

    def test_longest_phrase_wins_over_shorter_ambiguous_synonym(self, catalog):
        """'net revenue' contains 'revenue' (a gross_revenue synonym) as a
        substring, but the longer, more specific net_revenue name must win."""
        result = catalog.match("net revenue")
        assert isinstance(result, Match)
        assert result.metric == "net_revenue"

    def test_no_match_returns_none(self, catalog):
        assert catalog.match("banana smoothie recipe") is None

    def test_empty_question_returns_none(self, catalog):
        assert catalog.match("") is None
        assert catalog.match("   ") is None

    def test_word_boundary_prevents_partial_word_match(self, catalog):
        """'sales' (a gross_revenue synonym) must not match inside 'wholesales'."""
        assert catalog.match("wholesales report") is None

    def test_ambiguous_when_two_metrics_tie_on_phrase_length(self, catalog):
        tied = Catalog(
            dataset_id="test",
            metrics={
                "metric_a": MetricInfo(name="metric_a", label="Widget count"),
                "metric_b": MetricInfo(name="metric_b", label="Widget count"),
            },
        )
        result = tied.match("widget count")
        assert isinstance(result, Ambiguous)
        assert set(result.candidates) == {"metric_a", "metric_b"}

    def test_match_includes_dimensions_from_question(self, catalog):
        result = catalog.match("net revenue by channel")
        assert isinstance(result, Match)
        assert "orders.channel" in result.dimensions

    def test_phrase_pattern_cache_does_not_cross_contaminate_between_phrases(self, catalog):
        """_contains_phrase's compiled-pattern cache (added once catalog.match
        was found to recompile every phrase's regex on every call, ~20x
        slower against a few hundred metrics) is keyed by the phrase text
        itself -- confirm two different phrases still match independently
        rather than one cached pattern leaking into another's result."""
        assert catalog.match("net revenue") is not None
        result = catalog.match("gross revenue")
        assert isinstance(result, Match)
        assert result.metric == "gross_revenue"


class TestCatalogMatchDimensions:
    def test_matches_dimension_by_label(self, catalog):
        assert catalog.match_dimensions("group by channel") == ("orders.channel",)

    def test_matches_dimension_by_synonym(self, catalog):
        assert catalog.match_dimensions("split by sales channel") == ("orders.channel",)

    def test_no_dimension_mentioned_returns_empty(self, catalog):
        assert catalog.match_dimensions("net revenue") == ()


class TestCatalogIntrospection:
    def test_metric_names_sorted(self, catalog):
        assert catalog.metric_names() == ("gross_revenue", "net_revenue", "order_count")

    def test_dimension_names_sorted(self, catalog):
        assert catalog.dimension_names() == ("customers.email", "orders.channel")

    def test_pii_dimensions(self, catalog):
        assert catalog.pii_dimensions() == ("customers.email",)
