"""Time resolution: calendars, fiscal years, relative phrases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True)
class TimeRange:
    """Absolute date range with grain."""

    start: date
    end: date  # exclusive
    grain: str  # day | week | month | quarter | year | fiscal_quarter | fiscal_year
    basis: str | None = None


@dataclass(frozen=True)
class CalendarSpec:
    """Localization and fiscal calendar."""

    timezone: str = "UTC"
    week_start: str = "monday"  # monday | sunday | saturday
    fiscal_year_start_month: int = 1
    pattern: str = "gregorian"  # gregorian | 445 | 454 | 544
    holidays: tuple[date, ...] = ()


class TimeResolver(Protocol):
    """Deterministic time phrase resolution."""

    def resolve(self, phrase: str, *, now: datetime, cal: CalendarSpec) -> TimeRange:
        """Convert "last quarter" to absolute range."""
        ...
