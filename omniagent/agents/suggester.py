"""Suggest follow-up questions, deterministically, from what the catalog
knows and what this turn's query didn't already use.

Genuinely asynchronous/background dispatch (so suggestions don't add to
answer latency) is a channel-layer concern — Phase 8's service can fire this
after the answer is already returned. The selection logic itself has no
reason to involve a model: it is picking from a fixed catalog, not
generating novel text.
"""

from __future__ import annotations

from omniagent.agents.query_codec import query_from_dict
from omniagent.kernel.catalog import Catalog
from omniagent.kernel.state import OmniState

_MAX_SUGGESTIONS = 3
# Leave room for at least one alternate-metric suggestion rather than
# filling every slot with near-identical "by <dimension>" variants — a mix
# is more useful than three breakdowns of the same number.
_MAX_DIMENSION_SUGGESTIONS = 2


def suggest_followups(state: OmniState, catalog: Catalog) -> list[str]:
    if not state.semantic_query:
        return []

    query = query_from_dict(state.semantic_query)
    used_metrics = set(query.metrics)
    used_dims = set(query.group_by)
    suggestions: list[str] = []

    if not query.group_by:
        metric_label = catalog.metrics[query.metrics[0]].label if query.metrics else "this"
        for dim_name in catalog.dimension_names():
            if dim_name in used_dims:
                continue
            dim = catalog.dimensions[dim_name]
            if dim.is_pii:
                continue
            suggestions.append(f"{metric_label} by {dim.label}")
            if len(suggestions) >= _MAX_DIMENSION_SUGGESTIONS:
                break

    for metric_name in catalog.metric_names():
        if metric_name in used_metrics:
            continue
        suggestions.append(catalog.metrics[metric_name].label)
        if len(suggestions) >= _MAX_SUGGESTIONS:
            break

    return suggestions
