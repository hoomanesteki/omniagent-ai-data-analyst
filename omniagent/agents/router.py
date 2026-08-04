"""Router: one narrow LLM call deciding what an unmatched question needs.

Reached only when master_node's deterministic catalog match fully misses
(not ambiguous: ambiguous already has named candidates to offer without a
model call at all). A total miss could mean three different things, and
guessing which one produces the wrong user experience in two of the three
cases, so this makes exactly one narrow call to decide:

- a genuine out-of-scope data question the guarded SQL fallback should
  attempt (sql_agent can write a query even though no catalog metric
  matched by name)
- a question that needs more information before anything should run
  (paused via the interrupt()-based clarify node, not guessed at)
- a non-data intent (greeting, small talk, off-topic) that no amount of
  SQL generation or clarification could ever turn into a real answer
"""

from __future__ import annotations

from langgraph.graph import END
from langgraph.types import Command

from omniagent.agents.messages import latest_user_message
from omniagent.agents.node_types import GraphNode
from omniagent.kernel.catalog import Catalog
from omniagent.kernel.models import Route
from omniagent.kernel.ports.llm import LLMProvider
from omniagent.kernel.state import OmniState

_DEFAULT_ABSTAIN_NARRATION = "I can only answer questions about this dataset's metrics."


def make_router_node(
    *,
    catalog: Catalog,
    llm: LLMProvider,
    model_id: str,
    sql_route: str = "fast_path",
    clarify_route: str = "clarify",
) -> GraphNode:
    """Bind the catalog and model to a one-call intent router."""

    async def router_node(state: OmniState) -> Command[str]:
        question = latest_user_message(state)
        route = llm.structured(
            model_id,
            {
                "task": "route_question",
                "question": question,
                "known_metrics": [catalog.metrics[name].label for name in catalog.metric_names()],
            },
            schema=Route,
        )

        model_calls_by_node = dict(state.model_calls_by_node)
        model_calls_by_node["router"] = model_calls_by_node.get("router", 0) + 1
        base_update = {
            "llm_calls": state.llm_calls + 1,
            "model_calls_by_node": model_calls_by_node,
            "intent": route.intent,
        }

        if route.needs_clarification:
            return Command(
                goto=clarify_route,
                update={
                    **base_update,
                    "clarification": {
                        "question": route.rationale or "Could you clarify what you'd like to know?",
                        "options": list(route.clarification_options),
                    },
                },
            )

        if route.intent == "sql":
            return Command(goto=sql_route, update=base_update)

        return Command(
            goto=END,
            update={
                **base_update,
                "narration": route.rationale or _DEFAULT_ABSTAIN_NARRATION,
            },
        )

    return router_node
