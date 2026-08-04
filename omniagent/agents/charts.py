"""Deterministic chart-type selection from a result set's shape.

No model call: the right chart type is a function of how many metric and
dimension columns are present and what kind the dimension is (time vs.
categorical), not something that needs judgment per question.

Rule table (applied in order, first match wins):
  1. No rows, or 1 row with no group-by dimension -> no chart (a single KPI
     is a number, not a plot).
  2. 1 group-by dimension, time-typed -> line chart (trend over time).
  3. 1 group-by dimension, categorical/boolean -> bar chart, sorted
     descending by the first metric so the largest category reads first.
  4. 2 group-by dimensions -> grouped bar (first dimension on the x-axis,
     second as color/series) — kept to two dimensions for MVP; a third
     would need faceting, deferred past this phase.
  5. Anything else (3+ dimensions, or dimension type kernel doesn't know
     about) -> no chart; the table speaks for itself and a wrong chart
     guess is worse than no chart.
"""

from __future__ import annotations

from typing import Any

from omniagent.kernel import catalog as catalog_module
from omniagent.kernel.catalog import Catalog
from omniagent.kernel.models import ChartSpec
from omniagent.kernel.models import DisplayFormat as ContractDisplayFormat

# Validated categorical palette (light mode), fixed hue order — CVD-safe on
# every adjacent pair. Never cycle or reassign per-render; the order itself
# is the safety mechanism. See the dataviz skill's references/palette.md.
CATEGORICAL_PALETTE = [
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
]


def _to_contract_format(fmt: catalog_module.DisplayFormat) -> ContractDisplayFormat:
    """catalog.DisplayFormat is a lightweight internal value type (frozen,
    built straight from parsed pack YAML); models.DisplayFormat is the
    validated Pydantic contract ChartSpec actually carries across the
    agent/API boundary. They're structurally identical by coincidence, not
    the same type — convert explicitly rather than assume."""
    return ContractDisplayFormat(
        type=fmt.type,
        precision=fmt.precision,
        currency=fmt.currency,
        good_direction=fmt.good_direction,
    )


def choose_chart(
    *,
    result_set: list[dict[str, Any]] | None,
    group_by: tuple[str, ...],
    metrics: tuple[str, ...],
    catalog: Catalog,
) -> ChartSpec | None:
    if not result_set or not group_by:
        return None

    formats = {
        name: _to_contract_format(catalog.metrics[name].format)
        for name in metrics
        if name in catalog.metrics
    }

    if len(group_by) == 1:
        dim_name = group_by[0]
        dim_info = catalog.dimensions.get(dim_name)
        dim_field = _result_column_for_dimension(dim_name)
        metric_field = metrics[0]

        y_title = _metric_label(catalog, metric_field)

        if dim_info is not None and dim_info.type == "time":
            return ChartSpec(
                mark="line",
                encoding={
                    "x": {"field": dim_field, "type": "temporal", "title": dim_info.label},
                    "y": {"field": metric_field, "type": "quantitative", "title": y_title},
                    "tooltip": [
                        {"field": dim_field, "type": "temporal", "title": dim_info.label},
                        {"field": metric_field, "type": "quantitative", "title": y_title},
                    ],
                },
                title=y_title,
                formats=formats,
            )

        x_title = dim_info.label if dim_info else dim_field
        return ChartSpec(
            mark="bar",
            encoding={
                "x": {"field": dim_field, "type": "nominal", "title": x_title, "sort": "-y"},
                "y": {"field": metric_field, "type": "quantitative", "title": y_title},
                "tooltip": [
                    {"field": dim_field, "type": "nominal", "title": x_title},
                    {"field": metric_field, "type": "quantitative", "title": y_title},
                ],
            },
            title=y_title,
            formats=formats,
        )

    if len(group_by) == 2:
        x_dim, series_dim = group_by[0], group_by[1]
        x_info = catalog.dimensions.get(x_dim)
        series_info = catalog.dimensions.get(series_dim)
        metric_field = metrics[0]
        x_field = _result_column_for_dimension(x_dim)
        series_field = _result_column_for_dimension(series_dim)
        x_title = x_info.label if x_info else x_dim
        series_title = series_info.label if series_info else series_dim
        y_title = _metric_label(catalog, metric_field)

        return ChartSpec(
            mark="bar",
            encoding={
                "x": {"field": x_field, "type": "nominal", "title": x_title},
                "y": {"field": metric_field, "type": "quantitative", "title": y_title},
                "color": {
                    "field": series_field,
                    "type": "nominal",
                    "title": series_title,
                    # Fixed hue order, never cycled — see CATEGORICAL_PALETTE.
                    "scale": {"range": CATEGORICAL_PALETTE},
                },
                "tooltip": [
                    {"field": x_field, "type": "nominal", "title": x_title},
                    {"field": series_field, "type": "nominal", "title": series_title},
                    {"field": metric_field, "type": "quantitative", "title": y_title},
                ],
            },
            title=y_title,
            formats=formats,
        )

    return None


def _metric_label(catalog: Catalog, metric_name: str) -> str:
    info = catalog.metrics.get(metric_name)
    return info.label if info else metric_name


def _result_column_for_dimension(dim_name: str) -> str:
    """The compiler aliases a qualified dimension reference (model.field) to
    model__field in the SELECT list — see native_yaml.py's join/select
    aliasing. Chart encodings reference the same result-column name."""
    return dim_name.replace(".", "__")
