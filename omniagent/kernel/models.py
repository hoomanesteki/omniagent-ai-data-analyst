"""Pydantic models for typed contracts between agents."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Route(BaseModel):
    """Router output: intent classification and routing decision."""

    intent: str  # open registry: "metric", "sql", "clarify", "help", "chat"
    target: str  # destination node
    confidence: float = Field(ge=0.0, le=1.0)
    needs_clarification: bool = False
    clarification_options: list[str] = []
    rationale: str = ""

    class Config:
        extra = "forbid"


class SqlCandidate(BaseModel):
    """SQL generation output: a candidate query."""

    sql: str
    tables_used: list[str] = []
    reasoning: str = ""

    class Config:
        extra = "forbid"


class MetricValue(BaseModel):
    """A single metric value with formatting."""

    metric: str
    value: Any
    formatted: str = ""
    unit: Optional[str] = None
    currency: Optional[str] = None


class DisplayFormat(BaseModel):
    """Formatting directive for a metric."""

    type: str  # "number", "currency", "percent"
    precision: int = 2
    currency: Optional[str] = None
    good_direction: Optional[str] = None  # "up", "down"


class ChartSpec(BaseModel):
    """Chart specification in Vega-Lite terms."""

    mark: str  # registry key: "bar", "line", "scatter", "pie", etc.
    encoding: dict[str, Any] = {}
    title: str = ""
    subtitle: str = ""
    formats: dict[str, DisplayFormat] = {}

    class Config:
        extra = "forbid"


class Verdict(BaseModel):
    """Critic/judge output: assessment of an answer."""

    is_grounded: bool
    numbers_match: bool
    confidence: float = Field(ge=0.0, le=1.0)
    abstain: bool = False
    reason: Optional[str] = None

    class Config:
        extra = "forbid"


class AnswerEnvelope(BaseModel):
    """Versioned answer contract delivered to all channels."""

    envelope_version: str = "1"
    kind: str  # "answer" | "abstention" | "clarification"
    headline: Optional[str] = None
    narration: Optional[str] = None
    values: list[MetricValue] = []
    chart: Optional[ChartSpec] = None
    table_ref: Optional[str] = None
    executed_sql: Optional[str] = None
    metric_request: Optional[dict] = None
    confidence: Optional[float] = None
    assumptions: list[str] = []
    suggestions: list[str] = []
    clarification: Optional[dict] = None
    trace_id: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        extra = "forbid"


class Clarification(BaseModel):
    """User clarification request."""

    question: str
    options: list[str]
    selected: Optional[str] = None
