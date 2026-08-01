"""Typed state for the LangGraph state machine."""

from dataclasses import dataclass, field
from typing import Any, Annotated, Mapping, Optional

from operator import add


@dataclass
class OmniState:
    """Persistent state across a multi-turn conversation."""

    # Identity and scope
    principal: Mapping[str, str] = field(default_factory=dict)  # tenant, user, roles
    thread_id: str = ""
    dataset_id: str = ""
    schema_version: str = ""

    # Conversation
    messages: Annotated[list[dict], add] = field(default_factory=list)

    # Routing and intent
    intent: Optional[str] = None
    route: Optional[str] = None
    clarification: Optional[dict] = None

    # Semantic query path
    semantic_query: Optional[dict] = None
    metric_match_score: float = 0.0
    matched_metric: Optional[str] = None

    # SQL fallback path
    sql_candidates: Annotated[list[dict], add] = field(default_factory=list)
    executed_sql: Optional[str] = None

    # Results and evidence
    result_ref: Optional[str] = None
    result_meta: Optional[dict] = None
    evidence: Optional[dict] = None

    # Guard and narration
    guarded: Optional[dict] = None
    narration: Optional[str] = None
    chart_spec: Optional[dict] = None
    suggestions: Annotated[list[dict], add] = field(default_factory=list)
    confidence: Optional[float] = None
    assumptions: Annotated[list[str], add] = field(default_factory=list)

    # Escalation and budgeting
    tier_bump: int = 0
    llm_calls: int = 0
    model_calls_by_node: dict[str, int] = field(default_factory=dict)

    # Control flow
    needs_human: bool = False
    error: Optional[str] = None
