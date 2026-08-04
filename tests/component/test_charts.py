"""Component tests for deterministic chart-type selection, against the real
ecommerce pack's catalog (dimension types matter for line vs. bar)."""

import pytest

from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
from omniagent.agents.charts import choose_chart


@pytest.fixture
def catalog():
    return NativeYamlProvider("packs").catalog("ecommerce")


class TestNoChartCases:
    def test_no_result_set_returns_none(self, catalog):
        assert (
            choose_chart(result_set=None, group_by=(), metrics=("gross_revenue",), catalog=catalog)
            is None
        )

    def test_empty_result_set_returns_none(self, catalog):
        assert (
            choose_chart(result_set=[], group_by=(), metrics=("gross_revenue",), catalog=catalog)
            is None
        )

    def test_single_kpi_no_group_by_returns_none(self, catalog):
        result_set = [{"gross_revenue": 225.0}]
        assert (
            choose_chart(
                result_set=result_set, group_by=(), metrics=("gross_revenue",), catalog=catalog
            )
            is None
        )

    def test_three_dimensions_returns_none(self, catalog):
        result_set = [
            {
                "orders__channel": "web",
                "orders__payment_method": "card",
                "customers__country": "US",
                "gross_revenue": 10.0,
            }
        ]
        chart = choose_chart(
            result_set=result_set,
            group_by=("orders.channel", "orders.payment_method", "customers.country"),
            metrics=("gross_revenue",),
            catalog=catalog,
        )
        assert chart is None


class TestBarChart:
    def test_categorical_dimension_produces_bar(self, catalog):
        result_set = [
            {"orders__channel": "web", "gross_revenue": 150.0},
            {"orders__channel": "mobile_app", "gross_revenue": 75.0},
        ]
        chart = choose_chart(
            result_set=result_set,
            group_by=("orders.channel",),
            metrics=("gross_revenue",),
            catalog=catalog,
        )
        assert chart.mark == "bar"
        assert chart.encoding["x"]["field"] == "orders__channel"
        assert chart.encoding["x"]["type"] == "nominal"
        assert chart.encoding["y"]["field"] == "gross_revenue"
        assert chart.title == "Gross revenue"

    def test_bar_carries_currency_format(self, catalog):
        result_set = [{"orders__channel": "web", "gross_revenue": 150.0}]
        chart = choose_chart(
            result_set=result_set,
            group_by=("orders.channel",),
            metrics=("gross_revenue",),
            catalog=catalog,
        )
        assert chart.formats["gross_revenue"].type == "currency"
        assert chart.formats["gross_revenue"].currency == "USD"


class TestLineChart:
    def test_time_dimension_produces_line(self, catalog):
        result_set = [
            {"orders__order_date": "2026-01-01", "gross_revenue": 100.0},
            {"orders__order_date": "2026-02-01", "gross_revenue": 120.0},
        ]
        chart = choose_chart(
            result_set=result_set,
            group_by=("orders.order_date",),
            metrics=("gross_revenue",),
            catalog=catalog,
        )
        assert chart.mark == "line"
        assert chart.encoding["x"]["type"] == "temporal"


class TestGroupedBarChart:
    def test_two_dimensions_produces_grouped_bar_with_color_series(self, catalog):
        result_set = [
            {"orders__channel": "web", "customers__country": "US", "gross_revenue": 100.0},
        ]
        chart = choose_chart(
            result_set=result_set,
            group_by=("orders.channel", "customers.country"),
            metrics=("gross_revenue",),
            catalog=catalog,
        )
        assert chart.mark == "bar"
        assert chart.encoding["x"]["field"] == "orders__channel"
        assert chart.encoding["color"]["field"] == "customers__country"
