"""Unit tests for deterministic value formatting."""

import pytest

from omniagent.kernel.catalog import DisplayFormat
from omniagent.kernel.formatting import format_value


class TestCurrencyFormat:
    def test_usd_default_symbol(self):
        fmt = DisplayFormat(type="currency", precision=2, currency="USD")
        assert format_value(1234.5, fmt) == "$1,234.50"

    def test_eur_symbol(self):
        fmt = DisplayFormat(type="currency", precision=2, currency="EUR")
        assert format_value(99.9, fmt) == "€99.90"

    def test_unknown_currency_code_falls_back_to_prefix(self):
        fmt = DisplayFormat(type="currency", precision=2, currency="XYZ")
        assert format_value(10.0, fmt) == "XYZ 10.00"

    def test_zero_precision(self):
        fmt = DisplayFormat(type="currency", precision=0, currency="USD")
        assert format_value(1234.5, fmt) == "$1,234"

    def test_negative_value(self):
        fmt = DisplayFormat(type="currency", precision=2, currency="USD")
        assert format_value(-50.0, fmt) == "$-50.00"


class TestPercentFormat:
    def test_fraction_to_percent(self):
        fmt = DisplayFormat(type="percent", precision=2)
        assert format_value(0.3333, fmt) == "33.33%"

    def test_zero_precision_percent(self):
        fmt = DisplayFormat(type="percent", precision=0)
        assert format_value(0.5, fmt) == "50%"


class TestNumberFormat:
    def test_thousands_separator(self):
        fmt = DisplayFormat(type="number", precision=0)
        assert format_value(123456, fmt) == "123,456"

    def test_default_precision(self):
        fmt = DisplayFormat(type="number", precision=2)
        assert format_value(1.5, fmt) == "1.50"


class TestNonNumeric:
    @pytest.mark.parametrize("value", [None, "already text", ["a", "list"]])
    def test_non_numeric_value_stringified(self, value):
        fmt = DisplayFormat(type="number")
        assert format_value(value, fmt) == str(value)
