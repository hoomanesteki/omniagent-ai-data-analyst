"""Typed state for the LangGraph state machine."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from operator import add
from typing import Annotated, Any


@dataclass
class OmniState:
    """Persistent state across a multi-turn conversation."""

    # Identity and scope
    principal: Mapping[str, str] = field(default_factory=dict)  # tenant, user, roles
    thread_id: str = ""
    dataset_id: str = ""
    schema_version: str = ""

    # Conversation
    messages: Annotated[list[dict[str, Any]], add] = field(default_factory=list)

    # Routing and intent
    intent: str | None = None
    route: str | None = None
    clarification: dict[str, Any] | None = None

    # Semantic query path
    semantic_query: dict[str, Any] | None = None
    metric_match_score: float = 0.0
    matched_metric: str | None = None

    # SQL fallback path
    #
    # Not an `add`-reducer channel like `messages`: a node here always
    # returns the full accumulated value for this turn (same convention as
    # `llm_calls`/`model_calls_by_node` below), not a delta to append. With
    # a real checkpointer persisting state across separate `/ask` calls on
    # the same thread, an `add` reducer would keep concatenating a prior
    # turn's candidates onto every later turn's, unrelated question or not.
    sql_candidates: list[dict[str, Any]] = field(default_factory=list)
    executed_sql: str | None = None

    # Results and evidence
    result_ref: str | None = None
    result_meta: dict[str, Any] | None = None
    # Materialized, row_cap-bounded result rows, kept alongside result_ref so
    # gates (e.g. numeric_recompute) can verify narrated numbers in-process
    # without a round trip through the ResultStore.
    result_set: list[Any] | None = None
    evidence: dict[str, Any] | None = None

    # Guard and narration
    guarded: dict[str, Any] | None = None
    narration: str | None = None
    chart_spec: dict[str, Any] | None = None
    suggestions: Annotated[list[dict[str, Any]], add] = field(default_factory=list)
    confidence: float | None = None
    # Same "full value, not a delta" convention as `sql_candidates` above.
    # See that field's comment for why an `add` reducer would be wrong here
    # once a real checkpointer persists state across separate `/ask` calls.
    assumptions: list[str] = field(default_factory=list)

    # Escalation and budgeting
    tier_bump: int = 0
    llm_calls: int = 0
    model_calls_by_node: dict[str, int] = field(default_factory=dict)

    # Control flow
    needs_human: bool = False
    error: str | None = None
