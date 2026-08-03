"""Deterministic resolution of relative time phrases to absolute ranges.

Every range is half-open, ``[start, end)``, so adjacent periods tile without
overlap and a caller never has to reason about whether the last day is
included. No wall-clock reads: ``now`` is always injected, which is what makes
the resolver unit-testable and the answer ledger reproducible.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from omniagent.kernel.ports.time import CalendarSpec, TimeRange

_WEEK_START_INDEX = {"monday": 0, "sunday": 6, "saturday": 5}


class TimePhraseError(ValueError):
    """The phrase is not one the resolver understands."""


def _add_months(d: date, months: int) -> date:
    """Shift by whole months, clamping to the last valid day of the target month."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def _start_of_week(d: date, week_start: str) -> date:
    start_index = _WEEK_START_INDEX[week_start]
    delta = (d.weekday() - start_index) % 7
    return d - timedelta(days=delta)


def _fiscal_year_start(d: date, start_month: int) -> date:
    """First day of the fiscal year containing ``d``."""
    year = d.year if d.month >= start_month else d.year - 1
    return date(year, start_month, 1)


def _fiscal_quarter_start(d: date, start_month: int) -> date:
    """First day of the fiscal quarter containing ``d``."""
    fy_start = _fiscal_year_start(d, start_month)
    months_in = (d.year - fy_start.year) * 12 + (d.month - fy_start.month)
    return _add_months(fy_start, (months_in // 3) * 3)


class DefaultTimeResolver:
    """Resolve English relative time phrases against an injected ``now``.

    Recognised shapes:

    - ``today``, ``yesterday``
    - ``this|last|previous <week|month|quarter|year>``
    - ``this|last|previous <fiscal quarter|fiscal year>``
    - ``last N <days|weeks|months|quarters|years>``
    - ``year to date`` / ``ytd``, ``quarter to date`` / ``qtd``,
      ``month to date`` / ``mtd``, ``fiscal year to date``
    """

    _LAST_N = re.compile(r"^(?:last|past|previous)\s+(\d+)\s+(day|week|month|quarter|year)s?$")
    _RELATIVE = re.compile(
        r"^(this|current|last|previous|prior)\s+(fiscal\s+)?(week|month|quarter|year)$"
    )
    _TO_DATE = re.compile(r"^(fiscal\s+)?(year|quarter|month)[\s-]to[\s-]date$")

    def resolve(self, phrase: str, *, now: datetime, cal: CalendarSpec) -> TimeRange:
        today = now.date()
        text = " ".join(phrase.strip().lower().split())

        for handler in (
            self._resolve_literal,
            self._resolve_abbreviated_to_date,
            self._resolve_to_date,
            self._resolve_last_n,
            self._resolve_relative,
        ):
            resolved = handler(text, today, cal)
            if resolved is not None:
                return resolved

        raise TimePhraseError(f"Unrecognized time phrase: {phrase!r}")

    def _resolve_literal(self, text: str, today: date, cal: CalendarSpec) -> TimeRange | None:
        if text == "today":
            return TimeRange(start=today, end=today + timedelta(days=1), grain="day")
        if text == "yesterday":
            return TimeRange(start=today - timedelta(days=1), end=today, grain="day")
        return None

    def _resolve_abbreviated_to_date(
        self, text: str, today: date, cal: CalendarSpec
    ) -> TimeRange | None:
        abbreviations = {"ytd": "year-to-date", "qtd": "quarter-to-date", "mtd": "month-to-date"}
        if text in abbreviations:
            return self._resolve_to_date(abbreviations[text], today, cal)
        return None

    def _resolve_to_date(self, text: str, today: date, cal: CalendarSpec) -> TimeRange | None:
        match = self._TO_DATE.match(text)
        if not match:
            return None
        fiscal = bool(match.group(1))
        unit = match.group(2)
        end = today + timedelta(days=1)

        if unit == "year":
            if fiscal:
                start = _fiscal_year_start(today, cal.fiscal_year_start_month)
                return TimeRange(start=start, end=end, grain="fiscal_year", basis="to_date")
            return TimeRange(start=date(today.year, 1, 1), end=end, grain="year", basis="to_date")
        if unit == "quarter":
            if fiscal:
                start = _fiscal_quarter_start(today, cal.fiscal_year_start_month)
                return TimeRange(start=start, end=end, grain="fiscal_quarter", basis="to_date")
            start = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
            return TimeRange(start=start, end=end, grain="quarter", basis="to_date")
        return TimeRange(
            start=date(today.year, today.month, 1), end=end, grain="month", basis="to_date"
        )

    def _resolve_last_n(self, text: str, today: date, cal: CalendarSpec) -> TimeRange | None:
        match = self._LAST_N.match(text)
        if not match:
            return None
        count = int(match.group(1))
        unit = match.group(2)
        if count < 1:
            raise TimePhraseError("Period count must be at least 1")
        end = today + timedelta(days=1)

        if unit == "day":
            return TimeRange(start=end - timedelta(days=count), end=end, grain="day")
        if unit == "week":
            return TimeRange(start=end - timedelta(weeks=count), end=end, grain="week")
        if unit == "month":
            return TimeRange(start=_add_months(end, -count), end=end, grain="month")
        if unit == "quarter":
            return TimeRange(start=_add_months(end, -3 * count), end=end, grain="quarter")
        return TimeRange(start=_add_months(end, -12 * count), end=end, grain="year")

    def _resolve_relative(  # noqa: C901 - one branch per supported relative-phrase form
        self, text: str, today: date, cal: CalendarSpec
    ) -> TimeRange | None:
        match = self._RELATIVE.match(text)
        if not match:
            return None
        qualifier = match.group(1)
        fiscal = bool(match.group(2))
        unit = match.group(3)
        is_current = qualifier in ("this", "current")

        if fiscal and unit not in ("quarter", "year"):
            raise TimePhraseError(f"No fiscal {unit} — fiscal periods are quarters or years")

        if unit == "week":
            start = _start_of_week(today, cal.week_start)
            if not is_current:
                start -= timedelta(weeks=1)
            return TimeRange(start=start, end=start + timedelta(weeks=1), grain="week")

        if unit == "month":
            start = date(today.year, today.month, 1)
            if not is_current:
                start = _add_months(start, -1)
            return TimeRange(start=start, end=_add_months(start, 1), grain="month")

        if unit == "quarter":
            if fiscal:
                start = _fiscal_quarter_start(today, cal.fiscal_year_start_month)
                grain = "fiscal_quarter"
            else:
                start = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
                grain = "quarter"
            if not is_current:
                start = _add_months(start, -3)
            return TimeRange(start=start, end=_add_months(start, 3), grain=grain)

        if fiscal:
            start = _fiscal_year_start(today, cal.fiscal_year_start_month)
            grain = "fiscal_year"
        else:
            start = date(today.year, 1, 1)
            grain = "year"
        if not is_current:
            start = _add_months(start, -12)
        return TimeRange(start=start, end=_add_months(start, 12), grain=grain)
