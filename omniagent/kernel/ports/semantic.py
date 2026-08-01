"""Semantic layer provider: metrics, dimensions, compile to SQL."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class FilterOp(Enum):
    """Filter operators, vendor-neutral."""

    EQ = "eq"
    NEQ = "neq"
    IN = "in"
    NOT_IN = "not_in"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    BETWEEN = "between"
    CONTAINS = "contains"


@dataclass(frozen=True)
class Filter:
    """Structured filter: field, op, value."""

    field: str
    op: FilterOp
    value: Any


@dataclass(frozen=True)
class SemanticQuery:
    """Provider-neutral metrics query AST."""

    metrics: tuple[str, ...]
    group_by: tuple[str, ...] = ()
    filters: tuple[Filter, ...] = ()
    time_range: Any = None
    order_by: tuple[str, ...] = ()
    limit: int = 100
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class SemanticCapabilities:
    """Semantic provider feature flags."""

    ratio: bool
    derived: bool
    cumulative: bool
    conversion: bool
    percentiles: bool
    semi_additive: bool
    custom_calendar: bool


@dataclass(frozen=True)
class CompiledQuery:
    """Compiled query with provenance."""

    sql: str
    dialect: str
    provenance: dict[str, Any]


class SemanticIssue(Exception):
    """Validation issue in a SemanticQuery."""

    pass


class SemanticProvider(Protocol):
    """Metrics engine interface."""

    def catalog(self, dataset_id: str) -> Any:
        """Catalog of metrics and dimensions."""
        ...

    def schema_version(self, dataset_id: str) -> str:
        """Manifest hash for invalidation."""
        ...

    def validate(self, dataset_id: str, q: SemanticQuery) -> list[SemanticIssue]:
        """Check if query is valid. Empty list = valid."""
        ...

    def compile(self, dataset_id: str, q: SemanticQuery) -> CompiledQuery:
        """Compile SemanticQuery to SQL."""
        ...

    def capabilities(self) -> SemanticCapabilities:
        """Declared capabilities."""
        ...
