"""Master router: deterministic catalog matching, no model call.

If the question names a metric the catalog knows, there is nothing for an
LLM to decide — routing to the semantic agent is a pure function of the
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


def make_master_node(catalog: Catalog, *, fallback_route: str | None = None) -> GraphNode:
    """Bind a dataset's catalog and return the master node function.

    `fallback_route` names the node an unmatched question is sent to instead
    of an immediate clarification (e.g. "fast_path", ahead of the guarded SQL
    fallback) — an ambiguous match still always clarifies, since the catalog
    has genuine, discoverable candidates to offer; only a total miss has
    nothing better than "here's what I can answer" to fall back on without a
    fallback route configured.
    """

    async def master_node(state: OmniState) -> Command[str]:
        question = latest_user_message(state)
        result = catalog.match(question)

        if isinstance(result, Match):
            return Command(
                goto="semantic_agent",
                update={
                    "route": "semantic_agent",
                    "matched_metric": result.metric,
                    "metric_match_score": result.score,
                    "intent": "metric",
                },
            )

        if isinstance(result, Ambiguous):
            return Command(
                goto=END,
                update={
                    "route": "clarify",
                    "needs_human": True,
                    "clarification": {
                        "question": "Which metric did you mean?",
                        # Labels, not raw snake_case names — clicking one
                        # round-trips as the next question, and
                        # catalog.match() matches label text too. If two
                        # candidates ever share a label, the real packs
                        # never do (verified), and re-asking would be
                        # genuinely ambiguous to a human reader too, not
                        # just to the matcher.
                        "options": [catalog.metrics[name].label for name in result.candidates],
                    },
                },
            )

        # No deterministic match at all. Full model-based routing (Phase 6)
        # is not wired in yet. With a fallback route configured, try the
        # guarded SQL path instead of giving up immediately; without one,
        # the honest terminal state is to say what is actually supported
        # rather than guess.
        if fallback_route is not None:
            return Command(goto=fallback_route, update={"route": fallback_route, "intent": "sql"})

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

    return master_node
