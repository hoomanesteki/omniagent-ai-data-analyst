"""Serialize SemanticQuery to/from a plain dict for OmniState.semantic_query.

OmniState is a LangGraph state schema (checkpointed, possibly persisted), so
its fields stay JSON-plain rather than holding kernel dataclass/enum
instances directly.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from omniagent.kernel.ports.semantic import Filter, FilterOp, SemanticQuery
from omniagent.kernel.ports.time import TimeRange


def query_to_dict(q: SemanticQuery) -> dict[str, Any]:
    return {
        "metrics": list(q.metrics),
        "group_by": list(q.group_by),
        "filters": [{"field": f.field, "op": f.op.value, "value": f.value} for f in q.filters],
        "time_range": (
            {
                "start": q.time_range.start.isoformat(),
                "end": q.time_range.end.isoformat(),
                "grain": q.time_range.grain,
                "basis": q.time_range.basis,
            }
            if q.time_range is not None
            else None
        ),
        "order_by": list(q.order_by),
        "limit": q.limit,
        "assumptions": list(q.assumptions),
    }


def query_from_dict(d: dict[str, Any]) -> SemanticQuery:
    time_range: TimeRange | None = None
    raw_range = d.get("time_range")
    if raw_range is not None:
        time_range = TimeRange(
            start=date.fromisoformat(raw_range["start"]),
            end=date.fromisoformat(raw_range["end"]),
            grain=raw_range["grain"],
            basis=raw_range.get("basis"),
        )
    return SemanticQuery(
        metrics=tuple(d["metrics"]),
        group_by=tuple(d.get("group_by", ())),
        filters=tuple(
            Filter(field=f["field"], op=FilterOp(f["op"]), value=f["value"])
            for f in d.get("filters", ())
        ),
        time_range=time_range,
        order_by=tuple(d.get("order_by", ())),
        limit=d.get("limit", 100),
        assumptions=tuple(d.get("assumptions", ())),
    )
