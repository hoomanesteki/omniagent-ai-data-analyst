"""Unit tests for DefaultTimeResolver: deterministic phrase -> TimeRange.

`now` is always injected (never read from the wall clock), so every case
below is exact and reproducible.
"""

from datetime import date, datetime

import pytest

from omniagent.kernel.ports.time import CalendarSpec
from omniagent.kernel.time_resolver import DefaultTimeResolver, TimePhraseError

NOW = datetime(2026, 8, 3)  # a Monday
GREGORIAN = CalendarSpec()


@pytest.fixture
def resolver():
    return DefaultTimeResolver()


class TestLiteralPhrases:
    def test_today(self, resolver):
        r = resolver.resolve("today", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end, r.grain) == (date(2026, 8, 3), date(2026, 8, 4), "day")

    def test_yesterday(self, resolver):
        r = resolver.resolve("yesterday", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end, r.grain) == (date(2026, 8, 2), date(2026, 8, 3), "day")


class TestRelativePeriods:
    def test_this_month(self, resolver):
        r = resolver.resolve("this month", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end, r.grain) == (date(2026, 8, 1), date(2026, 9, 1), "month")

    def test_last_month(self, resolver):
        r = resolver.resolve("last month", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end, r.grain) == (date(2026, 7, 1), date(2026, 8, 1), "month")

    def test_last_month_across_year_boundary(self, resolver):
        r = resolver.resolve("last month", now=datetime(2026, 1, 15), cal=GREGORIAN)
        assert (r.start, r.end) == (date(2025, 12, 1), date(2026, 1, 1))

    def test_this_quarter(self, resolver):
        r = resolver.resolve("this quarter", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end, r.grain) == (date(2026, 7, 1), date(2026, 10, 1), "quarter")

    def test_last_quarter(self, resolver):
        r = resolver.resolve("last quarter", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end, r.grain) == (date(2026, 4, 1), date(2026, 7, 1), "quarter")

    def test_this_year(self, resolver):
        r = resolver.resolve("this year", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end, r.grain) == (date(2026, 1, 1), date(2027, 1, 1), "year")

    def test_last_year(self, resolver):
        r = resolver.resolve("last year", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end, r.grain) == (date(2025, 1, 1), date(2026, 1, 1), "year")

    def test_previous_is_synonym_for_last(self, resolver):
        assert resolver.resolve("previous quarter", now=NOW, cal=GREGORIAN) == resolver.resolve(
            "last quarter", now=NOW, cal=GREGORIAN
        )

    def test_current_is_synonym_for_this(self, resolver):
        assert resolver.resolve("current month", now=NOW, cal=GREGORIAN) == resolver.resolve(
            "this month", now=NOW, cal=GREGORIAN
        )

    def test_this_week_monday_start(self, resolver):
        r = resolver.resolve("this week", now=NOW, cal=GREGORIAN)  # NOW is a Monday
        assert (r.start, r.end, r.grain) == (date(2026, 8, 3), date(2026, 8, 10), "week")

    def test_last_week_monday_start(self, resolver):
        r = resolver.resolve("last week", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end) == (date(2026, 7, 27), date(2026, 8, 3))

    def test_this_week_sunday_start(self, resolver):
        cal = CalendarSpec(week_start="sunday")
        # NOW (Mon Aug 3) falls in the week starting Sunday Aug 2.
        r = resolver.resolve("this week", now=NOW, cal=cal)
        assert (r.start, r.end) == (date(2026, 8, 2), date(2026, 8, 9))


class TestFiscalPeriods:
    """A fiscal year starting in February is deliberately off the calendar
    quarter grid, so fiscal and gregorian results genuinely diverge."""

    FEBRUARY_FISCAL = CalendarSpec(fiscal_year_start_month=2)

    def test_last_fiscal_quarter_differs_from_calendar_quarter(self, resolver):
        fiscal = resolver.resolve("last fiscal quarter", now=NOW, cal=self.FEBRUARY_FISCAL)
        calendar = resolver.resolve("last quarter", now=NOW, cal=GREGORIAN)
        assert (fiscal.start, fiscal.end) == (date(2026, 5, 1), date(2026, 8, 1))
        assert (calendar.start, calendar.end) == (date(2026, 4, 1), date(2026, 7, 1))
        assert (fiscal.start, fiscal.end) != (calendar.start, calendar.end)
        assert fiscal.grain == "fiscal_quarter"

    def test_this_fiscal_quarter(self, resolver):
        r = resolver.resolve("this fiscal quarter", now=NOW, cal=self.FEBRUARY_FISCAL)
        assert (r.start, r.end) == (date(2026, 8, 1), date(2026, 11, 1))

    def test_last_fiscal_year(self, resolver):
        r = resolver.resolve("last fiscal year", now=NOW, cal=self.FEBRUARY_FISCAL)
        assert (r.start, r.end, r.grain) == (date(2025, 2, 1), date(2026, 2, 1), "fiscal_year")

    def test_this_fiscal_year(self, resolver):
        r = resolver.resolve("this fiscal year", now=NOW, cal=self.FEBRUARY_FISCAL)
        assert (r.start, r.end) == (date(2026, 2, 1), date(2027, 2, 1))

    def test_fiscal_week_is_rejected(self, resolver):
        """Fiscal periods are only quarters or years — a fiscal week has no meaning."""
        with pytest.raises(TimePhraseError):
            resolver.resolve("last fiscal week", now=NOW, cal=self.FEBRUARY_FISCAL)


class TestLastN:
    def test_last_n_days(self, resolver):
        r = resolver.resolve("last 30 days", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end, r.grain) == (date(2026, 7, 5), date(2026, 8, 4), "day")

    def test_last_n_weeks(self, resolver):
        r = resolver.resolve("last 2 weeks", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end, r.grain) == (date(2026, 7, 21), date(2026, 8, 4), "week")

    def test_last_n_months(self, resolver):
        r = resolver.resolve("last 3 months", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end, r.grain) == (date(2026, 5, 4), date(2026, 8, 4), "month")

    def test_last_n_quarters(self, resolver):
        r = resolver.resolve("last 2 quarters", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end, r.grain) == (date(2026, 2, 4), date(2026, 8, 4), "quarter")

    def test_last_n_years(self, resolver):
        r = resolver.resolve("last 2 years", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end, r.grain) == (date(2024, 8, 4), date(2026, 8, 4), "year")

    def test_past_n_is_synonym_for_last_n(self, resolver):
        assert resolver.resolve("past 7 days", now=NOW, cal=GREGORIAN) == resolver.resolve(
            "last 7 days", now=NOW, cal=GREGORIAN
        )

    def test_singular_unit_accepted(self, resolver):
        r = resolver.resolve("last 1 day", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end) == (date(2026, 8, 3), date(2026, 8, 4))


class TestToDate:
    def test_year_to_date(self, resolver):
        r = resolver.resolve("year to date", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end, r.grain, r.basis) == (
            date(2026, 1, 1),
            date(2026, 8, 4),
            "year",
            "to_date",
        )

    def test_ytd_abbreviation_matches_year_to_date(self, resolver):
        assert resolver.resolve("ytd", now=NOW, cal=GREGORIAN) == resolver.resolve(
            "year to date", now=NOW, cal=GREGORIAN
        )

    def test_quarter_to_date(self, resolver):
        r = resolver.resolve("quarter to date", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end) == (date(2026, 7, 1), date(2026, 8, 4))

    def test_qtd_abbreviation(self, resolver):
        assert resolver.resolve("qtd", now=NOW, cal=GREGORIAN) == resolver.resolve(
            "quarter to date", now=NOW, cal=GREGORIAN
        )

    def test_month_to_date(self, resolver):
        r = resolver.resolve("month to date", now=NOW, cal=GREGORIAN)
        assert (r.start, r.end) == (date(2026, 8, 1), date(2026, 8, 4))

    def test_mtd_abbreviation(self, resolver):
        assert resolver.resolve("mtd", now=NOW, cal=GREGORIAN) == resolver.resolve(
            "month to date", now=NOW, cal=GREGORIAN
        )

    def test_fiscal_year_to_date(self, resolver):
        cal = CalendarSpec(fiscal_year_start_month=2)
        r = resolver.resolve("fiscal year to date", now=NOW, cal=cal)
        assert (r.start, r.end, r.grain) == (date(2026, 2, 1), date(2026, 8, 4), "fiscal_year")


class TestErrorHandling:
    def test_unrecognized_phrase_raises(self, resolver):
        with pytest.raises(TimePhraseError):
            resolver.resolve("sometime last tuesday-ish", now=NOW, cal=GREGORIAN)

    def test_zero_count_rejected(self, resolver):
        with pytest.raises(TimePhraseError):
            resolver.resolve("last 0 days", now=NOW, cal=GREGORIAN)

    def test_phrase_is_case_and_whitespace_insensitive(self, resolver):
        assert resolver.resolve("  LAST   Quarter  ", now=NOW, cal=GREGORIAN) == resolver.resolve(
            "last quarter", now=NOW, cal=GREGORIAN
        )
