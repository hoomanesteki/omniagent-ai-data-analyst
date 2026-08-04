"""Master router: deterministic catalog matching, no model call.

If the question names a metric the catalog knows, there is nothing for an
LLM to decide: routing to the semantic agent is a pure function of the
catalog and the question text. An ambiguous or unmatched question is not a
failure state to paper over with a guess; it is routed to a clarification
so the caller can ask precisely, rather than confidently answering the
wrong question.
"""

from __future__ import annotations

from langgraph.graph import END
from langgraph.types import Command

from omniagent.agents.messages import latest_user_message
from omniagent.agents.node_types import GraphNode
from omniagent.kernel.catalog import Ambiguous, Catalog, Match
from omniagent.kernel.state import OmniState


def dispatch_match(
    result: Match | Ambiguous | None,
    catalog: Catalog,
    *,
    fallback_route: str | None = None,
    clarify_route: str | None = None,
) -> Command[str]:
    """Route a `catalog.match()` result to the right next node.

    Shared by `master_node` and the interrupt()-based `clarify_node`, so a
    clarification answer re-enters exactly the same dispatch logic as an
    original question: clicking a metric label round-trips through
    `catalog.match()` just like typing a fresh question would.

    `clarify_route` names a node that genuinely pauses execution (via
    `interrupt()`) to wait for an answer, used for the ambiguous case when
    one is configured. `fallback_route` names the node an unmatched
    question is sent to instead of an immediate plain clarification (e.g.
    "router", ahead of the guarded SQL fallback). Without either, both
    cases fall back to ending the turn with a `clarification` dict the
    caller must start a fresh turn to answer, matching this graph's
    behavior before Phase 6.
    """
    if isinstance(result, Match):
        return Command(
            goto="semantic_agent",
            update={
                "route": "semantic_agent",
                "matched_metric": result.metric,
                "metric_match_score": result.score,
                "intent": "metric",
                "clarification": None,
            },
        )

    if isinstance(result, Ambiguous):
        clarification = {
            "question": "Which metric did you mean?",
            # Labels, not raw snake_case names: clicking one round-trips as
            # the next question, and catalog.match() matches label text
            # too. If two candidates ever share a label, the real packs
            # never do (verified), and re-asking would be genuinely
            # ambiguous to a human reader too, not just to the matcher.
            "options": [catalog.metrics[name].label for name in result.candidates],
        }
        if clarify_route is not None:
            return Command(goto=clarify_route, update={"clarification": clarification})
        return Command(
            goto=END,
            update={"route": "clarify", "needs_human": True, "clarification": clarification},
        )

    # No deterministic match at all.
    if fallback_route is not None:
        return Command(
            goto=fallback_route,
            update={"route": fallback_route, "intent": "sql", "clarification": None},
        )

    return Command(
        goto=END,
        update={
            "route": "clarify",
            "needs_human": True,
            "clarification": {
                "question": (
                    "I couldn't match that to a known metric for this dataset. "
                    "Here's what I can answer:"
                ),
                "options": [catalog.metrics[name].label for name in catalog.metric_names()],
            },
        },
    )


def make_master_node(
    catalog: Catalog, *, fallback_route: str | None = None, clarify_route: str | None = None
) -> GraphNode:
    """Bind a dataset's catalog and return the master node function.

    See `dispatch_match` for what `fallback_route` and `clarify_route` do.
    """

    async def master_node(state: OmniState) -> Command[str]:
        question = latest_user_message(state)
        result = catalog.match(question)
        return dispatch_match(
            result, catalog, fallback_route=fallback_route, clarify_route=clarify_route
        )

    return master_node
