"""Pydantic models for typed contracts between agents."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Route(BaseModel):
    """Router output: intent classification and routing decision."""

    model_config = ConfigDict(extra="forbid")

    intent: str  # open registry: "metric", "sql", "clarify", "help", "chat"
    target: str  # destination node
    confidence: float = Field(ge=0.0, le=1.0)
    needs_clarification: bool = False
    clarification_options: list[str] = []
    rationale: str = ""


class FilterExtraction(BaseModel):
    """One filter the model spotted in the question."""

    model_config = ConfigDict(extra="forbid")

    dimension: str  # a dimension name/synonym the model believes it recognized
    value: str


class SemanticExtraction(BaseModel):
    """Semantic agent's one LLM call: pull free-text time/filter context out
    of the question. Metric and group-by dimension identification stay
    deterministic (catalog matching) — this call exists only for the parts
    that genuinely need language understanding: spotting a time expression
    and any explicit filter values.
    """

    model_config = ConfigDict(extra="forbid")

    time_phrase: str | None = None  # e.g. "last quarter"; null if none present
    filters: list[FilterExtraction] = []


class SqlCandidate(BaseModel):
    """SQL generation output: a candidate query."""

    model_config = ConfigDict(extra="forbid")

    sql: str
    tables_used: list[str] = []
    reasoning: str = ""


class MetricValue(BaseModel):
    """A single metric value with formatting."""

    metric: str
    value: Any
    formatted: str = ""
    unit: str | None = None
    currency: str | None = None


class DisplayFormat(BaseModel):
    """Formatting directive for a metric."""

    type: str  # "number", "currency", "percent"
    precision: int = 2
    currency: str | None = None
    good_direction: str | None = None  # "up", "down"


class ChartSpec(BaseModel):
    """Chart specification in Vega-Lite terms."""

    model_config = ConfigDict(extra="forbid")

    mark: str  # registry key: "bar", "line", "scatter", "pie", etc.
    encoding: dict[str, Any] = {}
    title: str = ""
    subtitle: str = ""
    formats: dict[str, DisplayFormat] = {}


class Verdict(BaseModel):
    """Critic/judge output: assessment of an answer."""

    model_config = ConfigDict(extra="forbid")

    is_grounded: bool
    numbers_match: bool
    confidence: float = Field(ge=0.0, le=1.0)
    abstain: bool = False
    reason: str | None = None


class AnswerEnvelope(BaseModel):
    """Versioned answer contract delivered to all channels."""

    model_config = ConfigDict(extra="forbid")

    envelope_version: str = "1"
    kind: str  # "answer" | "abstention" | "clarification"
    headline: str | None = None
    narration: str | None = None
    values: list[MetricValue] = []
    chart: ChartSpec | None = None
    table_ref: str | None = None
    executed_sql: str | None = None
    metric_request: dict[str, Any] | None = None
    confidence: float | None = None
    assumptions: list[str] = []
    suggestions: list[str] = []
    clarification: dict[str, Any] | None = None
    trace_id: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Clarification(BaseModel):
    """User clarification request."""

    question: str
    options: list[str]
    selected: str | None = None
