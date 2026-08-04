"""Governed graph: master -> semantic_agent -> executor -> narrator.

This wires the deterministic-first path: a question either matches the
catalog deterministically and flows through to a governed, gate-checked,
narrated answer, or it terminates early in a clarification (master) or an
error (semantic_agent/executor) — narrator only runs once executor has a
real result to describe. The SQL fallback (Phase 5) and model-based router
(Phase 6) attach to this same graph later without changing this wiring.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from omniagent.agents.executor import make_executor_node
from omniagent.agents.master import make_master_node
from omniagent.agents.narrator import make_narrator_node
from omniagent.agents.semantic_agent import make_semantic_agent_node
from omniagent.kernel.catalog import Catalog
from omniagent.kernel.gates import GuardrailPolicy
from omniagent.kernel.ports.engine import EngineAdapter
from omniagent.kernel.ports.llm import LLMProvider
from omniagent.kernel.ports.semantic import SemanticProvider
from omniagent.kernel.ports.time import CalendarSpec, TimeResolver
from omniagent.kernel.state import OmniState


def build_governed_graph(
    *,
    dataset_id: str,
    catalog: Catalog,
    semantic_provider: SemanticProvider,
    engine: EngineAdapter,
    llm: LLMProvider,
    model_id: str,
    time_resolver: TimeResolver,
    guardrail_policy: GuardrailPolicy,
    calendar: CalendarSpec | None = None,
    now_fn: Callable[[], datetime] | None = None,
    principal: Any = None,
    row_cap: int = 10_000,
    timeout_s: float = 30.0,
    gate_config: dict[str, Any] | None = None,
) -> CompiledStateGraph[OmniState, None, OmniState, OmniState]:
    """Assemble and compile the governed graph for one dataset."""
    graph: StateGraph[OmniState, None, OmniState, OmniState] = StateGraph(OmniState)

    # langgraph's add_node overloads are typed against its internal _Node
    # protocol family and don't (in this version's stubs) model a bare
    # `async def node(state) -> Command[...]` callable directly, even though
    # that is a supported, documented node shape and works correctly at
    # runtime (exercised end-to-end in tests/integration). Stub gap, not a
    # real type error here.
    graph.add_node("master", make_master_node(catalog))  # type: ignore[call-overload]
    graph.add_node(  # type: ignore[call-overload]
        "semantic_agent",
        make_semantic_agent_node(
            dataset_id=dataset_id,
            catalog=catalog,
            semantic_provider=semantic_provider,
            llm=llm,
            model_id=model_id,
            time_resolver=time_resolver,
            calendar=calendar or CalendarSpec(),
            now_fn=now_fn or (lambda: datetime.now(UTC)),
        ),
    )
    graph.add_node(  # type: ignore[call-overload]
        "executor",
        make_executor_node(
            dataset_id=dataset_id,
            semantic_provider=semantic_provider,
            engine=engine,
            guardrail_policy=guardrail_policy,
            principal=principal,
            row_cap=row_cap,
            timeout_s=timeout_s,
            gate_config=gate_config,
        ),
    )
    graph.add_node("narrator", make_narrator_node(catalog))  # type: ignore[call-overload]

    graph.add_edge(START, "master")
    graph.add_edge("narrator", END)

    return graph.compile()
