"""Semantic provider backed by a single YAML file per dataset.

This is the primary provider. It compiles a ``SemanticQuery`` to SQL in-process
with no subprocess, no manifest build step, and no network — which is what
keeps a governed answer inside its latency budget and makes the plan cache
worth having.

Two properties matter more than anything else here:

**Values are never interpolated.** Every filter value becomes a bound
parameter, so a value that arrives from a model or an end user cannot terminate
a string and become SQL.

**Measures at different grains are never joined.** A single flat join across
orders and returns would multiply every order total by that order's return
count. Each measure is instead aggregated in its own subquery at its own grain,
and the subqueries are joined on the requested dimensions only. Where a
requested grouping *would* fan a measure out, compilation fails with an
explanation rather than returning a plausible wrong number.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

import yaml

from omniagent.kernel.catalog import Catalog, DimensionInfo, DisplayFormat, MetricInfo
from omniagent.kernel.ports.semantic import (
    CompiledQuery,
    Filter,
    FilterOp,
    SemanticCapabilities,
    SemanticIssue,
    SemanticQuery,
)
from omniagent.kernel.ports.time import TimeRange

_AGGREGATIONS = {
    "sum": "SUM({expr})",
    "count": "COUNT({expr})",
    "count_distinct": "COUNT(DISTINCT {expr})",
    "avg": "AVG({expr})",
    "min": "MIN({expr})",
    "max": "MAX({expr})",
}

_COMPARISON_OPS = {
    FilterOp.EQ: "=",
    FilterOp.NEQ: "<>",
    FilterOp.GT: ">",
    FilterOp.GTE: ">=",
    FilterOp.LT: "<",
    FilterOp.LTE: "<=",
}

_GRAINS = ("day", "week", "month", "quarter", "year")

ONE_TO_MANY = "one_to_many"
MANY_TO_ONE = "many_to_one"


@dataclass(frozen=True)
class _Measure:
    name: str
    model: str
    agg: str
    expr: str

    @property
    def qualified(self) -> str:
        return f"{self.model}.{self.name}"

    def sql(self) -> str:
        return _AGGREGATIONS[self.agg].format(expr=f"{self.model}.{self.expr}")


@dataclass(frozen=True)
class _Dimension:
    name: str
    model: str
    type: str
    expr: str
    label: str
    synonyms: tuple[str, ...] = ()
    is_pii: bool = False

    @property
    def qualified(self) -> str:
        return f"{self.model}.{self.name}"

    def sql(self, grain: str | None = None) -> str:
        column = f"{self.model}.{self.expr}"
        if grain:
            return f"DATE_TRUNC('{grain}', {column})"
        return column


@dataclass(frozen=True)
class _Model:
    name: str
    table: str
    primary_key: str | None
    join_to: str | None
    join_type: str
    join_condition: str | None
    relationship: str


@dataclass(frozen=True)
class _Metric:
    name: str
    label: str
    type: str  # simple | ratio | derived
    description: str = ""
    measure: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    expr: str | None = None
    depends_on: tuple[str, ...] = ()
    filters: tuple[Filter, ...] = ()
    default_time_dimension: str | None = None
    format: DisplayFormat = field(default_factory=DisplayFormat)
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True)
class _DimensionRef:
    """A dimension as referenced by a query: optionally with a time grain."""

    dimension: _Dimension
    grain: str | None

    @property
    def alias(self) -> str:
        base = f"{self.dimension.model}__{self.dimension.name}"
        return f"{base}__{self.grain}" if self.grain else base

    def sql(self) -> str:
        return self.dimension.sql(self.grain)


class NativeYamlProvider:
    """Compile ``SemanticQuery`` objects against a YAML metric definition."""

    def __init__(self, pack_root: str | Path, *, dialect: str = "duckdb"):
        self._root = Path(pack_root)
        self._dialect = dialect
        self._packs: dict[str, dict[str, Any]] = {}

    def capabilities(self) -> SemanticCapabilities:
        return SemanticCapabilities(
            ratio=True,
            derived=True,
            cumulative=False,
            conversion=False,
            percentiles=False,
            semi_additive=False,
            custom_calendar=False,
        )

    def catalog(self, dataset_id: str) -> Catalog:
        pack = self._load(dataset_id)
        metrics = {
            name: MetricInfo(
                name=name,
                label=metric.label,
                description=metric.description,
                synonyms=metric.synonyms,
                format=metric.format,
                default_grain="month",
            )
            for name, metric in pack["metrics"].items()
        }
        dimensions = {
            name: DimensionInfo(
                name=name,
                label=dimension.label,
                type=dimension.type,
                synonyms=dimension.synonyms,
                is_pii=dimension.is_pii,
            )
            for name, dimension in pack["dimensions"].items()
        }
        return Catalog(dataset_id=dataset_id, metrics=metrics, dimensions=dimensions)

    def schema_version(self, dataset_id: str) -> str:
        """Content hash of the pack file — changes invalidate cached plans."""
        return cast(str, self._load(dataset_id)["schema_version"])

    def validate(  # noqa: C901 - reports every problem with the query, not just the first
        self, dataset_id: str, q: SemanticQuery
    ) -> list[SemanticIssue]:
        """Every problem with the query, not just the first one."""
        pack = self._load(dataset_id)
        issues: list[SemanticIssue] = []

        if not q.metrics:
            issues.append(SemanticIssue("Query requests no metrics"))

        for metric_name in q.metrics:
            if metric_name not in pack["metrics"]:
                issues.append(
                    SemanticIssue(
                        f"Unknown metric {metric_name!r}. "
                        f"Known metrics: {', '.join(sorted(pack['metrics']))}"
                    )
                )

        for dimension_name in q.group_by:
            issues.extend(_dimension_issues(pack, dimension_name))

        for filter_ in q.filters:
            field_issues = _dimension_issues(pack, filter_.field, allow_grain=False)
            if field_issues:
                issues.extend(field_issues)
            elif filter_.op in (FilterOp.IN, FilterOp.NOT_IN) and not isinstance(
                filter_.value, (list, tuple, set)
            ):
                issues.append(
                    SemanticIssue(
                        f"Filter on {filter_.field!r} with {filter_.op.value} needs a list"
                    )
                )
            elif filter_.op is FilterOp.BETWEEN and (
                not isinstance(filter_.value, (list, tuple)) or len(filter_.value) != 2
            ):
                issues.append(
                    SemanticIssue(
                        f"Filter on {filter_.field!r} with between needs exactly two bounds"
                    )
                )

        selectable = (
            set(q.metrics) | {_dimension_alias(name) for name in q.group_by} | set(q.group_by)
        )
        for order_field in q.order_by:
            if order_field.lstrip("-") not in selectable:
                issues.append(
                    SemanticIssue(
                        f"Cannot order by {order_field.lstrip('-')!r}: not selected by the query"
                    )
                )

        if q.limit <= 0:
            issues.append(SemanticIssue("Limit must be positive"))

        if q.time_range is not None and not isinstance(q.time_range, TimeRange):
            issues.append(SemanticIssue("time_range must be a resolved TimeRange"))

        if not issues:
            # Fan-out is only detectable once the join paths are known, so it is
            # checked by a dry compile rather than by inspecting the query.
            try:
                _QueryPlan(pack, q, dialect=self._dialect).build()
            except SemanticIssue as exc:
                issues.append(exc)

        return issues

    def compile(self, dataset_id: str, q: SemanticQuery) -> CompiledQuery:
        """Compile to parameterised SQL, refusing anything that does not validate."""
        issues = self.validate(dataset_id, q)
        if issues:
            raise SemanticIssue("; ".join(str(issue) for issue in issues))

        pack = self._load(dataset_id)
        plan = _QueryPlan(pack, q, dialect=self._dialect)
        sql, params = plan.build()

        return CompiledQuery(
            sql=sql,
            dialect=self._dialect,
            provenance={
                "dataset_id": dataset_id,
                "schema_version": pack["schema_version"],
                "metrics": list(q.metrics),
                "group_by": list(q.group_by),
                "tables": sorted(plan.tables_used),
                "params": params,
                "filters": [
                    {"field": f.field, "op": f.op.value, "value": f.value} for f in q.filters
                ],
                "time_range": (
                    {
                        "start": q.time_range.start.isoformat(),
                        "end": q.time_range.end.isoformat(),
                        "grain": q.time_range.grain,
                    }
                    if isinstance(q.time_range, TimeRange)
                    else None
                ),
                "assumptions": list(q.assumptions) + plan.assumptions,
            },
        )

    def _load(self, dataset_id: str) -> dict[str, Any]:
        if dataset_id in self._packs:
            return self._packs[dataset_id]

        path = self._root / dataset_id / "semantic.yml"
        if not path.exists():
            raise SemanticIssue(f"No semantic pack for dataset {dataset_id!r} at {path}")

        raw_text = path.read_text()
        pack = _parse_pack(yaml.safe_load(raw_text))
        pack["schema_version"] = hashlib.sha256(raw_text.encode()).hexdigest()[:16]
        self._packs[dataset_id] = pack
        return pack


def _split_grain(reference: str) -> tuple[str, str | None]:
    """``orders.order_date__month`` -> ``("orders.order_date", "month")``."""
    if "__" in reference:
        base, _, suffix = reference.rpartition("__")
        if suffix in _GRAINS:
            return base, suffix
    return reference, None


def _dimension_alias(reference: str) -> str:
    return reference.replace(".", "__")


def _dimension_issues(
    pack: dict[str, Any], reference: str, *, allow_grain: bool = True
) -> list[SemanticIssue]:
    base, grain = _split_grain(reference)
    if grain and not allow_grain:
        return [SemanticIssue(f"Filter field {reference!r} may not carry a time grain")]
    if base not in pack["dimensions"]:
        return [
            SemanticIssue(
                f"Unknown dimension {base!r}. "
                f"Known dimensions: {', '.join(sorted(pack['dimensions']))}"
            )
        ]
    if grain and pack["dimensions"][base].type != "time":
        return [
            SemanticIssue(
                f"Dimension {base!r} is not a time dimension, so {grain!r} does not apply"
            )
        ]
    return []


def _parse_pack(raw: dict[str, Any]) -> dict[str, Any]:
    """Turn the YAML document into resolved model, dimension, and metric maps."""
    models: dict[str, _Model] = {}
    dimensions: dict[str, _Dimension] = {}
    measures: dict[str, _Measure] = {}

    for model_name, model_raw in (raw.get("models") or {}).items():
        join = model_raw.get("join") or {}
        relationship = join.get("relationship", MANY_TO_ONE)
        if join and relationship not in (ONE_TO_MANY, MANY_TO_ONE):
            raise SemanticIssue(
                f"Model {model_name!r} declares unsupported relationship {relationship!r}"
            )
        models[model_name] = _Model(
            name=model_name,
            table=model_raw["table"],
            primary_key=model_raw.get("primary_key"),
            join_to=join.get("to"),
            join_type=join.get("type", "left"),
            join_condition=join.get("condition"),
            relationship=relationship,
        )
        if join and not join.get("condition"):
            raise SemanticIssue(f"Model {model_name!r} declares a join with no condition")

        for dim_name, dim_raw in (model_raw.get("dimensions") or {}).items():
            dimension = _Dimension(
                name=dim_name,
                model=model_name,
                type=dim_raw.get("type", "categorical"),
                expr=dim_raw.get("expr", dim_name),
                label=dim_raw.get("label", dim_name.replace("_", " ").capitalize()),
                synonyms=tuple(dim_raw.get("synonyms") or ()),
                is_pii=bool(dim_raw.get("pii", False)),
            )
            dimensions[dimension.qualified] = dimension

        for measure_name, measure_raw in (model_raw.get("measures") or {}).items():
            agg = measure_raw.get("agg", "sum")
            if agg not in _AGGREGATIONS:
                raise SemanticIssue(
                    f"Unsupported aggregation {agg!r} on {model_name}.{measure_name}"
                )
            measure = _Measure(
                name=measure_name,
                model=model_name,
                agg=agg,
                expr=measure_raw.get("expr", measure_name),
            )
            measures[measure.qualified] = measure

    metrics: dict[str, _Metric] = {}
    for metric_name, metric_raw in (raw.get("metrics") or {}).items():
        format_raw = metric_raw.get("format") or {}
        metrics[metric_name] = _Metric(
            name=metric_name,
            label=metric_raw.get("label", metric_name.replace("_", " ").capitalize()),
            type=metric_raw.get("type", "simple"),
            description=str(metric_raw.get("description", "")).strip(),
            measure=metric_raw.get("measure"),
            numerator=metric_raw.get("numerator"),
            denominator=metric_raw.get("denominator"),
            expr=metric_raw.get("expr"),
            depends_on=tuple(metric_raw.get("depends_on") or ()),
            filters=tuple(_parse_filter(f) for f in (metric_raw.get("filters") or ())),
            default_time_dimension=metric_raw.get("default_time_dimension"),
            format=DisplayFormat(
                type=format_raw.get("type", "number"),
                precision=int(format_raw.get("precision", 2)),
                currency=format_raw.get("currency"),
                good_direction=format_raw.get("good_direction"),
            ),
            synonyms=tuple(metric_raw.get("synonyms") or ()),
        )

    _check_references(models, measures, dimensions, metrics)

    return {
        "dataset_id": raw["dataset_id"],
        "label": raw.get("label", raw["dataset_id"]),
        "description": str(raw.get("description", "")).strip(),
        "models": models,
        "dimensions": dimensions,
        "measures": measures,
        "metrics": metrics,
    }


def _parse_filter(raw: dict[str, Any]) -> Filter:
    return Filter(field=raw["field"], op=FilterOp(raw["op"]), value=raw["value"])


def _check_references(  # noqa: C901 - exhaustive reference validation, one branch per rule
    models: dict[str, _Model],
    measures: dict[str, _Measure],
    dimensions: dict[str, _Dimension],
    metrics: dict[str, _Metric],
) -> None:
    """Fail at load time on a pack that could not compile, not at question time."""
    for model in models.values():
        if model.join_to and model.join_to not in models:
            raise SemanticIssue(f"Model {model.name!r} joins to unknown model {model.join_to!r}")

    roots = [name for name, model in models.items() if model.join_to is None]
    if len(roots) != 1:
        raise SemanticIssue(
            f"Pack must have exactly one root model, found {len(roots)}: {sorted(roots)}"
        )

    for metric in metrics.values():
        for filter_ in metric.filters:
            if filter_.field not in dimensions:
                raise SemanticIssue(
                    f"Metric {metric.name!r} filters on unknown dimension {filter_.field!r}"
                )
        if metric.default_time_dimension and metric.default_time_dimension not in dimensions:
            raise SemanticIssue(
                f"Metric {metric.name!r} declares unknown time dimension "
                f"{metric.default_time_dimension!r}"
            )

        if metric.type == "simple":
            if metric.measure not in measures:
                raise SemanticIssue(
                    f"Metric {metric.name!r} references unknown measure {metric.measure!r}"
                )
        elif metric.type == "ratio":
            for role, ref in (
                ("numerator", metric.numerator),
                ("denominator", metric.denominator),
            ):
                if ref not in metrics:
                    raise SemanticIssue(f"Metric {metric.name!r} {role} {ref!r} is not a metric")
        elif metric.type == "derived":
            if not metric.expr:
                raise SemanticIssue(f"Derived metric {metric.name!r} has no expr")
            if not metric.depends_on:
                raise SemanticIssue(f"Derived metric {metric.name!r} declares no depends_on")
            for ref in metric.depends_on:
                if ref not in metrics:
                    raise SemanticIssue(f"Metric {metric.name!r} depends on unknown metric {ref!r}")
        else:
            raise SemanticIssue(f"Metric {metric.name!r} has unsupported type {metric.type!r}")

    _check_no_cycles(metrics)


def _check_no_cycles(metrics: dict[str, _Metric]) -> None:
    """A metric that transitively depends on itself would recurse forever."""
    white, grey, black = 0, 1, 2
    colour = dict.fromkeys(metrics, white)

    def visit(name: str, trail: tuple[str, ...]) -> None:
        if colour[name] == grey:
            raise SemanticIssue(f"Metric dependency cycle: {' -> '.join((*trail, name))}")
        if colour[name] == black:
            return
        colour[name] = grey
        metric = metrics[name]
        for dependency in _direct_dependencies(metric):
            visit(dependency, (*trail, name))
        colour[name] = black

    for name in metrics:
        visit(name, ())


def _direct_dependencies(metric: _Metric) -> tuple[str, ...]:
    if metric.type == "ratio":
        return (metric.numerator or "", metric.denominator or "")
    if metric.type == "derived":
        return metric.depends_on
    return ()


class _QueryPlan:
    """Assemble one statement from a validated query.

    Each measure model that the query touches becomes its own aggregate
    subquery at its own grain. The subqueries are then joined on the requested
    dimensions, which is what keeps a metric from being multiplied by an
    unrelated table's row count.
    """

    def __init__(self, pack: dict[str, Any], q: SemanticQuery, *, dialect: str):
        self._pack = pack
        self._q = q
        self._dialect = dialect
        self._params: list[Any] = []
        self.tables_used: set[str] = set()
        self.assumptions: list[str] = []
        self._group_refs = tuple(self._resolve_ref(name) for name in q.group_by)

    def build(self) -> tuple[str, list[Any]]:
        blocks = self._plan_blocks()
        subqueries = [self._build_subquery(block, f"m{i}") for i, block in enumerate(blocks)]

        select_parts = [
            f"{self._coalesced(ref, len(subqueries))} AS {ref.alias}" for ref in self._group_refs
        ]
        select_parts.extend(
            f"{self._metric_expression(name, blocks)} AS {name}" for name in self._q.metrics
        )

        lines = [f"SELECT {', '.join(select_parts)}", f"FROM {subqueries[0]} AS m0"]
        for index, subquery in enumerate(subqueries[1:], start=1):
            alias = f"m{index}"
            if self._group_refs:
                # Null-safe equality: a NULL group key is a real bucket, and
                # plain `=` would drop it from the joined result.
                conditions = " AND ".join(
                    f"m0.{ref.alias} IS NOT DISTINCT FROM {alias}.{ref.alias}"
                    for ref in self._group_refs
                )
                lines.append(f"FULL OUTER JOIN {subquery} AS {alias} ON {conditions}")
            else:
                lines.append(f"CROSS JOIN {subquery} AS {alias}")

        order_sql = self._order_clause()
        if order_sql:
            lines.append(f"ORDER BY {order_sql}")
        lines.append(f"LIMIT {int(self._q.limit)}")

        return "\n".join(lines), self._params

    def _plan_blocks(self) -> list[_Block]:
        """Partition the required simple metrics into independently-aggregated blocks."""
        blocks: dict[tuple[str, str | None], _Block] = {}
        for name in self._required_simple_metrics():
            metric = self._pack["metrics"][name]
            measure = self._pack["measures"][metric.measure]
            time_dimension = self._time_dimension_for(metric)
            key = (measure.model, time_dimension.qualified if time_dimension else None)
            block = blocks.get(key)
            if block is None:
                block = _Block(root=measure.model, time_dimension=time_dimension)
                blocks[key] = block
            block.metrics.append(name)
        return [blocks[key] for key in sorted(blocks, key=lambda k: (k[0], k[1] or ""))]

    def _required_simple_metrics(self) -> list[str]:
        """Every simple metric the requested metrics resolve to, in stable order."""
        ordered: list[str] = []
        seen: set[str] = set()

        def walk(name: str) -> None:
            if name in seen:
                return
            seen.add(name)
            metric = self._pack["metrics"][name]
            if metric.type == "simple":
                ordered.append(name)
                return
            for dependency in _direct_dependencies(metric):
                walk(dependency)

        for name in self._q.metrics:
            walk(name)
        return ordered

    def _build_subquery(self, block: _Block, alias: str) -> str:
        models = self._models_for_block(block)
        joins = self._join_path(block.root, models)

        select_parts = [f"{ref.sql()} AS {ref.alias}" for ref in self._group_refs]
        for name in block.metrics:
            metric = self._pack["metrics"][name]
            measure = self._pack["measures"][metric.measure]
            select_parts.append(f"{self._scoped_measure(measure, metric)} AS {name}")

        lines = [
            f"SELECT {', '.join(select_parts)}",
            f"FROM {self._pack['models'][block.root].table} AS {block.root}",
        ]
        lines.extend(joins)

        conditions = [self._filter_sql(f) for f in self._q.filters]
        time_condition = self._time_condition(block)
        if time_condition:
            conditions.append(time_condition)
        if conditions:
            lines.append(f"WHERE {' AND '.join(conditions)}")
        if self._group_refs:
            lines.append(f"GROUP BY {', '.join(str(i + 1) for i in range(len(self._group_refs)))}")

        indented = "\n".join(f"  {line}" for line in lines)
        return f"(\n{indented}\n)"

    def _scoped_measure(self, measure: _Measure, metric: _Metric) -> str:
        """Apply a metric's own filters to that metric alone.

        Putting them in the subquery's WHERE would silently re-scope every
        other metric aggregated alongside it.
        """
        aggregate = measure.sql()
        if not metric.filters:
            return aggregate
        conditions = " AND ".join(self._filter_sql(f) for f in metric.filters)
        return f"{aggregate} FILTER (WHERE {conditions})"

    def _models_for_block(self, block: _Block) -> set[str]:
        models = {block.root}
        for name in block.metrics:
            metric = self._pack["metrics"][name]
            for filter_ in metric.filters:
                models.add(self._dimension(filter_.field).model)
        for ref in self._group_refs:
            models.add(ref.dimension.model)
        for filter_ in self._q.filters:
            models.add(self._dimension(filter_.field).model)
        if block.time_dimension is not None:
            models.add(block.time_dimension.model)
        return models

    def _join_path(  # noqa: C901 - BFS over the join graph with several edge-shape branches
        self, root: str, models: set[str]
    ) -> list[str]:
        """Emit joins reaching every model in ``models`` from ``root``.

        Refuses any traversal that would multiply the root's rows, since that
        is exactly the silent double-counting the semantic layer exists to
        prevent.
        """
        pack_models: dict[str, _Model] = self._pack["models"]
        adjacency: dict[str, list[tuple[str, str]]] = {name: [] for name in pack_models}
        for model in pack_models.values():
            if model.join_to is None:
                continue
            # From the child's side, reaching its parent collapses rows; from
            # the parent's side, reaching the child multiplies them.
            child_to_parent = MANY_TO_ONE if model.relationship == MANY_TO_ONE else ONE_TO_MANY
            parent_to_child = ONE_TO_MANY if model.relationship == MANY_TO_ONE else MANY_TO_ONE
            adjacency[model.name].append((model.join_to, child_to_parent))
            adjacency[model.join_to].append((model.name, parent_to_child))

        parent: dict[str, str] = {}
        visited = {root}
        queue = [root]
        while queue:
            current = queue.pop(0)
            for neighbour, direction in adjacency[current]:
                if neighbour in visited:
                    continue
                if direction == ONE_TO_MANY:
                    if neighbour in models:
                        raise SemanticIssue(
                            f"Cannot group or filter this metric by {neighbour!r}: "
                            f"joining {root!r} to {neighbour!r} repeats each {root} row, "
                            f"which would multiply the measure. Use a metric defined on "
                            f"{neighbour!r} instead."
                        )
                    continue
                visited.add(neighbour)
                parent[neighbour] = current
                queue.append(neighbour)

        unreachable = models - visited
        if unreachable:
            raise SemanticIssue(
                f"Cannot join {', '.join(sorted(unreachable))} to {root!r} without fanning out"
            )

        needed: set[str] = set()
        for model_name in models:
            cursor = model_name
            while cursor != root:
                needed.add(cursor)
                cursor = parent[cursor]

        joins: list[str] = []
        emitted = {root}
        for model_name in sorted(needed, key=lambda name: self._depth(name, parent, root)):
            model = pack_models[model_name]
            # The type and condition are written on whichever model declared
            # the join, so take both from there rather than from the
            # traversal direction. `model` itself only owns them when its
            # own `join_to` is the edge being traversed; otherwise the
            # parent declared this edge (model_name.join_to pointing
            # elsewhere, or nowhere), and using model's own join_type/
            # join_condition here would silently splice in an unrelated
            # join it declared in a different direction.
            owner = model if model.join_to is not None and model.join_to in emitted else None
            if owner is None:
                owner = pack_models[parent[model_name]]
            joins.append(
                f"{owner.join_type.upper()} JOIN {model.table} AS {model_name} ON {owner.join_condition}"
            )
            emitted.add(model_name)

        for model_name in emitted:
            self.tables_used.add(pack_models[model_name].table)
        return joins

    @staticmethod
    def _depth(name: str, parent: dict[str, str], root: str) -> int:
        depth = 0
        cursor = name
        while cursor != root:
            cursor = parent[cursor]
            depth += 1
        return depth

    def _metric_expression(self, name: str, blocks: list[_Block]) -> str:
        metric = self._pack["metrics"][name]
        if metric.type == "simple":
            for index, block in enumerate(blocks):
                if name in block.metrics:
                    return f"m{index}.{name}"
            raise SemanticIssue(f"Metric {name!r} was not planned")
        if metric.type == "ratio":
            numerator = self._metric_expression(metric.numerator, blocks)
            denominator = self._metric_expression(metric.denominator, blocks)
            self.assumptions.append(f"{name} is NULL where {metric.denominator} is zero")
            return f"({numerator}) / NULLIF({denominator}, 0)"
        expr = metric.expr or ""
        for dependency in sorted(metric.depends_on, key=len, reverse=True):
            expr = expr.replace(
                dependency, f"COALESCE({self._metric_expression(dependency, blocks)}, 0)"
            )
        return f"({expr})"

    def _coalesced(self, ref: _DimensionRef, block_count: int) -> str:
        """Take the group key from whichever subquery has it on this row."""
        if block_count == 1:
            return f"m0.{ref.alias}"
        sources = ", ".join(f"m{i}.{ref.alias}" for i in range(block_count))
        return f"COALESCE({sources})"

    def _time_condition(self, block: _Block) -> str:
        time_range = self._q.time_range
        if not isinstance(time_range, TimeRange):
            return ""
        if block.time_dimension is None:
            raise SemanticIssue(
                "Query has a time range but no metric in this block declares a time dimension"
            )
        column = block.time_dimension.sql()
        self._params.extend([time_range.start, time_range.end])
        return f"{column} >= ? AND {column} < ?"

    def _time_dimension_for(self, metric: _Metric) -> _Dimension | None:
        """Explicit time grouping wins over the metric's declared default.

        The default is only resolved when the query actually carries a time
        range to filter by — pulling in its model unconditionally would force
        a join that exists purely to support a filter nothing is asking for,
        and that join can legitimately be fan-out-unsafe (e.g. a per-customer
        metric joined to its per-order default time dimension).
        """
        for ref in self._group_refs:
            if ref.dimension.type == "time":
                return ref.dimension
        if metric.default_time_dimension and self._q.time_range is not None:
            return self._dimension(metric.default_time_dimension)
        return None

    def _filter_sql(self, filter_: Filter) -> str:
        column = self._dimension(filter_.field).sql()
        value = filter_.value

        if filter_.op in _COMPARISON_OPS:
            self._params.append(value)
            return f"{column} {_COMPARISON_OPS[filter_.op]} ?"
        if filter_.op in (FilterOp.IN, FilterOp.NOT_IN):
            values = list(value)
            if not values:
                # An empty IN list is a query for nothing; say so explicitly
                # rather than emitting SQL engines disagree about.
                return "1 = 0" if filter_.op is FilterOp.IN else "1 = 1"
            self._params.extend(values)
            placeholders = ", ".join("?" for _ in values)
            keyword = "IN" if filter_.op is FilterOp.IN else "NOT IN"
            return f"{column} {keyword} ({placeholders})"
        if filter_.op is FilterOp.BETWEEN:
            low, high = value
            self._params.extend([low, high])
            return f"{column} BETWEEN ? AND ?"
        if filter_.op is FilterOp.CONTAINS:
            self._params.append(f"%{value}%")
            return f"{column} LIKE ?"
        raise SemanticIssue(f"Unsupported filter op {filter_.op!r}")

    def _order_clause(self) -> str:
        terms: list[str] = []
        for order_field in self._q.order_by:
            descending = order_field.startswith("-")
            name = order_field.lstrip("-")
            alias = _dimension_alias(name) if name in self._q.group_by else name
            terms.append(f"{alias} DESC" if descending else f"{alias} ASC")
        return ", ".join(terms)

    def _resolve_ref(self, reference: str) -> _DimensionRef:
        base, grain = _split_grain(reference)
        return _DimensionRef(dimension=self._dimension(base), grain=grain)

    def _dimension(self, name: str) -> _Dimension:
        base, _ = _split_grain(name)
        try:
            return cast(_Dimension, self._pack["dimensions"][base])
        except KeyError:
            raise SemanticIssue(f"Unknown dimension {name!r}") from None


@dataclass
class _Block:
    """One aggregate subquery: a measure model plus the metrics computed on it."""

    root: str
    time_dimension: _Dimension | None
    metrics: list[str] = field(default_factory=list)


def plan_cache_key(dataset_id: str, schema_version: str, q: SemanticQuery) -> str:
    """Stable key for a compiled plan.

    Includes ``schema_version`` so a pack edit invalidates cached SQL instead of
    serving a plan built against definitions that no longer exist.
    """
    payload = {
        "dataset_id": dataset_id,
        "schema_version": schema_version,
        "metrics": list(q.metrics),
        "group_by": list(q.group_by),
        "filters": [[f.field, f.op.value, _stable(f.value)] for f in q.filters],
        "order_by": list(q.order_by),
        "limit": q.limit,
        "time_range": (
            [
                q.time_range.start.isoformat(),
                q.time_range.end.isoformat(),
                q.time_range.grain,
            ]
            if isinstance(q.time_range, TimeRange)
            else None
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()[:32]


def _stable(value: Any) -> Any:
    if isinstance(value, (list, tuple, set)):
        return sorted((_stable(v) for v in value), key=str)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
