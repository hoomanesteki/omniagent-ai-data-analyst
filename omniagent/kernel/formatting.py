"""Deterministic value formatting from a metric's declared DisplayFormat.

No model call is ever involved in turning a number into display text — the
format is a property of the metric (declared once in the pack), not
something to infer per-question.
"""

from __future__ import annotations

from omniagent.kernel.catalog import DisplayFormat

_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}


def format_value(value: object, fmt: DisplayFormat) -> str:
    """Render a numeric value per its declared format, or str() for anything else."""
    if not isinstance(value, (int, float)):
        return str(value)

    if fmt.type == "currency":
        symbol = _CURRENCY_SYMBOLS.get(fmt.currency or "USD", (fmt.currency or "") + " ")
        return f"{symbol}{value:,.{fmt.precision}f}"

    if fmt.type == "percent":
        return f"{value * 100:.{fmt.precision}f}%"

    if fmt.precision == 0:
        return f"{value:,.0f}"
    return f"{value:,.{fmt.precision}f}"
