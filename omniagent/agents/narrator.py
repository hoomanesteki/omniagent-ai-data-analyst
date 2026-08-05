"""Narrator: template-first narration, deterministic confidence, chart, and
the decision of whether a critic pass is worth its cost.

Narration is never model-generated in this design — every number in it came
straight out of the result set, formatted per the metric's declared
DisplayFormat, and assembled from a template chosen by the result's shape.
A single-KPI answer costs zero LLM calls end to end (master's deterministic
match + semantic_agent's one extraction call + this template = the whole
turn). The "conditional critic" is a separate, occasional groundedness
check (Phase 9 wires the actual judge call) — not part of generating text.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END
from langgraph.types import Command

from omniagent.agents.charts import choose_chart
from omniagent.agents.node_types import GraphNode
from omniagent.agents.query_codec import query_from_dict
from omniagent.kernel.catalog import Catalog, DisplayFormat
from omniagent.kernel.formatting import format_value
from omniagent.kernel.state import OmniState

# Below this confidence, or when any assumption was recorded (an unresolved
# time phrase, a dropped filter), the answer is worth the extra scrutiny of
# a critic pass. Above it with no assumptions, the deterministic pipeline
# already accounts for everything that could have gone wrong, so a critic
# call would just spend tokens confirming what the gates already checked.
CRITIC_CONFIDENCE_THRESHOLD = 0.85

# The guarded SQL fallback (fast_path/sql_agent) has no deterministic catalog
# match behind it -- a model wrote the SQL, or a cache replayed one a model
# wrote earlier. That is strictly less trustworthy than any governed catalog
# match (0.9-1.0, see Catalog.match's own scoring), so its base confidence
# starts below the governed floor rather than defaulting to the same 1.0 a
# perfect name match gets.
_FALLBACK_BASE_CONFIDENCE = 0.6

_DEFAULT_FORMAT = DisplayFormat()


def compute_confidence(state: OmniState) -> float:
    """Combine the catalog match score with penalties for every place the
    pipeline had to guess or drop something, deterministically — never a
    model's self-reported confidence."""
    if state.route == "semantic_agent":
        confidence = state.metric_match_score or 1.0
    else:
        # Guarded fallback: no semantic_query, no catalog match score.
        confidence = _FALLBACK_BASE_CONFIDENCE

    if state.assumptions:
        confidence -= 0.1 * len(state.assumptions)

    result_meta = state.result_meta or {}
    if result_meta.get("truncated"):
        confidence -= 0.1

    return max(0.0, min(1.0, confidence))


def needs_critic(state: OmniState, confidence: float) -> bool:
    return confidence < CRITIC_CONFIDENCE_THRESHOLD or bool(state.assumptions)


def _format_metric(catalog: Catalog, metric_name: str, value: Any) -> str:
    info = catalog.metrics.get(metric_name)
    fmt = info.format if info else _DEFAULT_FORMAT
    return format_value(value, fmt)


def _metric_label(catalog: Catalog, metric_name: str) -> str:
    info = catalog.metrics.get(metric_name)
    return info.label if info else metric_name


def _narrate_single_kpi(metric_name: str, value: Any, catalog: Catalog) -> str:
    label = _metric_label(catalog, metric_name)
    formatted = _format_metric(catalog, metric_name, value)
    return f"{label} was {formatted}."


def _narrate_multi_metric_single_row(
    metrics: tuple[str, ...], row: dict[str, Any], catalog: Catalog
) -> str:
    parts = [
        f"{_metric_label(catalog, name)}: {_format_metric(catalog, name, row.get(name))}"
        for name in metrics
    ]
    return "; ".join(parts) + "."


def _sortable_metric_value(row: dict[str, Any], metric_name: str) -> float:
    """A NULL/missing metric value sorts last, never as a `0.0` that could
    beat a genuine negative value (a margin, a delta) into the "leader" spot,
    and never picked as the top group when any real value exists."""
    value = row.get(metric_name)
    return float(value) if isinstance(value, (int, float)) else float("-inf")


def _narrate_breakdown(
    metric_name: str,
    group_by: tuple[str, ...],
    result_set: list[dict[str, Any]],
    catalog: Catalog,
    *,
    limit: int | None = None,
) -> str:
    label = _metric_label(catalog, metric_name)
    dim_field = group_by[0].replace(".", "__")

    sorted_rows = sorted(
        result_set,
        key=lambda r: _sortable_metric_value(r, metric_name),
        reverse=True,
    )
    top = sorted_rows[0]
    top_label = top.get(dim_field, "?")
    top_raw_value = top.get(metric_name)
    n_more = len(sorted_rows) - 1

    if top_raw_value is None:
        # Every group's value is NULL -- there is no real leader to name.
        return (
            f"{label} breaks down across {len(sorted_rows)} groups, with no value for any of them."
        )

    top_value = _format_metric(catalog, metric_name, top_raw_value)

    if n_more <= 0:
        return f"{label} for {top_label} was {top_value}."

    # The compiler caps a breakdown at `limit` rows (see semantic_agent.py);
    # when the result set is exactly at that cap, there may be more real
    # groups than were fetched, so "breaks down across N groups" would
    # understate the true count. Ordered descending by the metric (also
    # semantic_agent.py), the *top* group is still correct either way.
    if limit is not None and len(sorted_rows) >= limit:
        return (
            f"{label} breaks down across at least {len(sorted_rows)} groups; "
            f"{top_label} leads at {top_value}."
        )
    return (
        f"{label} breaks down across {len(sorted_rows)} groups; {top_label} leads at {top_value}."
    )


def _narrate_fallback(result_set: list[dict[str, Any]]) -> str:
    """Generic narration for the guarded SQL fallback: there is no semantic
    metric/dimension shape to describe here (the SQL was model-written or
    replayed from a cache, not compiled from a catalog match), so this
    describes the actual rows rather than fabricating a metric-style claim."""
    if len(result_set) == 1:
        row = result_set[0]
        if len(row) == 1:
            ((key, value),) = row.items()
            return f"{key.replace('_', ' ')}: {value}."
        parts = [f"{key.replace('_', ' ')}: {value}" for key, value in row.items()]
        return "; ".join(parts) + "."
    return f"Returned {len(result_set)} rows."


def narrate(state: OmniState, catalog: Catalog) -> tuple[str, Any]:
    """Return (narration, chart_spec_or_none). Pure function of state — no I/O."""
    if not state.result_set:
        return "No results.", None

    if not state.semantic_query:
        # The guarded SQL fallback (fast_path/sql_agent) never sets
        # semantic_query -- there is no compiled metric/group_by shape to
        # narrate from, only the raw rows themselves. Falling through to
        # the governed templates below would incorrectly report "No
        # results." over a real result set (they require semantic_query).
        return _narrate_fallback(state.result_set), None

    query = query_from_dict(state.semantic_query)
    metric_name = query.metrics[0] if query.metrics else ""

    if len(state.result_set) == 1 and not query.group_by:
        row = state.result_set[0]
        if len(query.metrics) > 1:
            narration = _narrate_multi_metric_single_row(query.metrics, row, catalog)
        else:
            narration = _narrate_single_kpi(metric_name, row.get(metric_name), catalog)
    else:
        narration = _narrate_breakdown(
            metric_name, query.group_by, state.result_set, catalog, limit=query.limit
        )

    chart = choose_chart(
        result_set=state.result_set,
        group_by=query.group_by,
        metrics=query.metrics,
        catalog=catalog,
    )
    return narration, chart


def make_narrator_node(catalog: Catalog) -> GraphNode:
    """Bind a dataset's catalog and return the narrator node function."""

    async def narrator_node(state: OmniState) -> Command[str]:
        if state.error:
            # An upstream node already ended the turn with an error; nothing
            # to narrate.
            return Command(goto=END, update={})

        narration, chart = narrate(state, catalog)
        confidence = compute_confidence(state)

        chart_dict = chart.model_dump() if chart is not None else None

        return Command(
            goto=END,
            update={
                "narration": narration,
                "chart_spec": chart_dict,
                "confidence": confidence,
            },
        )

    return narrator_node
