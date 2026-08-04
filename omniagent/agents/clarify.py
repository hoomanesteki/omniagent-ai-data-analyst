"""Clarify: pause the graph and wait for the user's answer via interrupt().

Reached from master (an ambiguous match) or the router (a question that
needs more information). This genuinely pauses execution here rather than
ending the turn: the caller resumes with `Command(resume=answer)` and the
same run continues from exactly this point, with the rest of state already
intact. Requires a checkpointer compiled into the graph; `interrupt()`
raises without one.

The resumed answer re-enters the exact same deterministic dispatch as an
original question (`dispatch_match`), so clicking a clarification option (a
metric label) round-trips through `catalog.match()` exactly like master
does for a fresh question, and a still-ambiguous answer comes right back
through this same node for another round rather than needing special
handling.
"""

from __future__ import annotations

from langgraph.types import Command, interrupt

from omniagent.agents.master import dispatch_match
from omniagent.agents.node_types import GraphNode
from omniagent.kernel.catalog import Catalog
from omniagent.kernel.state import OmniState

_DEFAULT_PROMPT = {"question": "Could you clarify what you'd like to know?", "options": []}


def make_clarify_node(*, catalog: Catalog, fallback_route: str | None = None) -> GraphNode:
    """Bind the catalog and return an interrupt()-based clarification node."""

    async def clarify_node(state: OmniState) -> Command[str]:
        prompt = state.clarification or _DEFAULT_PROMPT
        answer = interrupt(prompt)

        result = catalog.match(str(answer))
        command = dispatch_match(
            result, catalog, fallback_route=fallback_route, clarify_route="clarify"
        )
        return Command(
            goto=command.goto,
            update={
                **(command.update or {}),
                "messages": [{"role": "user", "content": str(answer)}],
            },
        )

    return clarify_node
