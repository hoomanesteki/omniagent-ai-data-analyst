"""Golden set generator: backwards generation (enumerate, compile, execute, paraphrase).

For each metric the catalog knows, build a real SemanticQuery, compile and
execute it against the real warehouse to get ground truth, then attach one
or more natural-language phrasings that should resolve to the same query.

Paraphrasing here is template-based (deterministic, no API key needed), not
an LLM call: this generator's job is producing many distinct phrasings of a
question whose ground truth is already known for certain (it came from
actually executing the compiled query), which a template can do as well as
a model can for this purpose. A richer, LLM-based paraphrase step is a
plausible upgrade for phrasing variety once eval/ is run with a real key,
but the ground truth itself never depends on that either way.

Every golden item is generated fresh from the pack YAML and the live
warehouse rather than checked in as static data, since it is fully
deterministic (no randomness anywhere in this module) and this way it can
never drift out of sync with either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from omniagent.kernel.catalog import Catalog
from omniagent.kernel.ports.engine import EngineAdapter
from omniagent.kernel.ports.semantic import CompiledQuery, SemanticProvider, SemanticQuery

_SINGLE_METRIC_TEMPLATES = (
    "What was {label}?",
    "Show me {label}",
    "{label}?",
    "How much {label_lower} did we have?",
)

_BREAKDOWN_TEMPLATES = (
    "{label} by {dim_label}",
    "Show {label} broken down by {dim_label}",
    "What was {label} for each {dim_label_lower}?",
)


@dataclass(frozen=True)
class GoldenItem:
    """One golden question: a phrasing paired with the exact query and
    result it should produce, both obtained by actually compiling and
    executing that query, not by hand-computing an expected value."""

    item_id: str
    dataset_id: str
    question: str
    expected_metric: str
    expected_group_by: tuple[str, ...]
    gold_sql: str
    gold_result: list[dict[str, Any]] = field(default_factory=list)
    category: str = "single_metric"  # "single_metric" | "breakdown"


def _rows_from_execution(
    engine: EngineAdapter, compiled: CompiledQuery, *, principal: Any, row_cap: int
) -> list[dict[str, Any]]:
    result = engine.execute(
        compiled.sql,
        params=compiled.provenance.get("params", ()),
        principal=principal,
        timeout_s=30.0,
        row_cap=row_cap,
    )
    return [dict(zip(result.columns, row, strict=True)) for row in result.batches]


def generate_golden_set(
    *,
    dataset_id: str,
    catalog: Catalog,
    semantic_provider: SemanticProvider,
    engine: EngineAdapter,
    principal: Any = None,
    row_cap: int = 100,
) -> list[GoldenItem]:
    """Enumerate every metric (and one valid breakdown per metric, where the
    catalog has a dimension that compiles cleanly against it), compile and
    execute each against the real warehouse, and attach several template
    phrasings per query. Skips a metric/dimension combination outright if
    the semantic provider itself rejects it, rather than guessing at one
    that might fan out or otherwise fail."""
    items: list[GoldenItem] = []

    for metric_name in catalog.metric_names():
        metric = catalog.metrics[metric_name]

        single_query = SemanticQuery(metrics=(metric_name,), limit=row_cap)
        if semantic_provider.validate(dataset_id, single_query):
            continue
        compiled = semantic_provider.compile(dataset_id, single_query)
        rows = _rows_from_execution(engine, compiled, principal=principal, row_cap=row_cap)

        for i, template in enumerate(_SINGLE_METRIC_TEMPLATES):
            items.append(
                GoldenItem(
                    item_id=f"{dataset_id}-{metric_name}-single-{i}",
                    dataset_id=dataset_id,
                    question=template.format(label=metric.label, label_lower=metric.label.lower()),
                    expected_metric=metric_name,
                    expected_group_by=(),
                    gold_sql=compiled.sql,
                    gold_result=rows,
                    category="single_metric",
                )
            )

        breakdown_dim = _first_valid_breakdown_dimension(
            dataset_id, metric_name, catalog, semantic_provider
        )
        if breakdown_dim is None:
            continue

        dim_info = catalog.dimensions[breakdown_dim]
        breakdown_query = SemanticQuery(
            metrics=(metric_name,), group_by=(breakdown_dim,), limit=row_cap
        )
        breakdown_compiled = semantic_provider.compile(dataset_id, breakdown_query)
        breakdown_rows = _rows_from_execution(
            engine, breakdown_compiled, principal=principal, row_cap=row_cap
        )

        for i, template in enumerate(_BREAKDOWN_TEMPLATES):
            items.append(
                GoldenItem(
                    item_id=f"{dataset_id}-{metric_name}-breakdown-{i}",
                    dataset_id=dataset_id,
                    question=template.format(
                        label=metric.label,
                        dim_label=dim_info.label,
                        dim_label_lower=dim_info.label.lower(),
                    ),
                    expected_metric=metric_name,
                    expected_group_by=(breakdown_dim,),
                    gold_sql=breakdown_compiled.sql,
                    gold_result=breakdown_rows,
                    category="breakdown",
                )
            )

    return items


def _first_valid_breakdown_dimension(
    dataset_id: str, metric_name: str, catalog: Catalog, semantic_provider: SemanticProvider
) -> str | None:
    for dim_name, dim_info in catalog.dimensions.items():
        if dim_info.type != "categorical":
            continue
        query = SemanticQuery(metrics=(metric_name,), group_by=(dim_name,), limit=10)
        if not semantic_provider.validate(dataset_id, query):
            return dim_name
    return None
