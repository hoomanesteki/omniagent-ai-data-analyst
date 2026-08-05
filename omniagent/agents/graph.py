"""Governed graph: master -> semantic_agent -> executor -> narrator,
with two optional attachments layered on top of that core path.

Guarded SQL fallback (Phase 5): master -> fast_path -> sql_agent -> narrator,
active once `verified_query_store` is supplied. A cache-first check against
previously verified queries, then live model-generated SQL, both behind the
same gate stack the governed path uses.

Routing and durability (Phase 6): master -> router -> clarify/fast_path,
active once `checkpointer` is supplied (router additionally needs
`verified_query_store`, since its "sql" branch targets fast_path). The
router makes one narrow call to tell a genuine out-of-scope data question
apart from a non-data intent or a question that needs more information; the
`clarify` node genuinely pauses execution via `interrupt()` rather than
ending the turn, and a caller resumes it with `Command(resume=answer)`.

Without either attachment, an unmatched question still terminates in
master's plain clarification, and an ambiguous question still ends the turn
with a `clarification` dict the caller must start a fresh turn to answer,
exactly as before Phase 5/6.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from omniagent.agents.clarify import make_clarify_node
from omniagent.agents.executor import make_executor_node
from omniagent.agents.fast_path import make_fast_path_node
from omniagent.agents.master import make_master_node
from omniagent.agents.narrator import make_narrator_node
from omniagent.agents.node_types import GraphNode
from omniagent.agents.router import make_router_node
from omniagent.agents.semantic_agent import make_semantic_agent_node
from omniagent.agents.sql_agent import make_sql_agent_node
from omniagent.kernel.catalog import Catalog
from omniagent.kernel.gates import GuardrailPolicy
from omniagent.kernel.ports.engine import EngineAdapter
from omniagent.kernel.ports.llm import LLMProvider
from omniagent.kernel.ports.semantic import SemanticProvider
from omniagent.kernel.ports.stores import VerifiedQueryStore
from omniagent.kernel.ports.time import CalendarSpec, TimeResolver
from omniagent.kernel.state import OmniState
from omniagent.kernel.telemetry import Tracer


def _traced(name: str, node_fn: GraphNode, tracers: dict[str, Tracer] | None) -> GraphNode:
    """Wrap a node so every call records a masked-input span, without
    changing any node's own code. `tracers` is a caller-owned dict keyed by
    thread_id: since dicts are passed by reference, the caller reads
    completed spans back out of the same object it passed in here, and
    `build_governed_graph`'s return type never has to change to carry a
    trace out alongside the compiled graph."""
    if tracers is None:
        return node_fn

    async def wrapped(state: OmniState) -> Command[str]:
        tracer = tracers.setdefault(state.thread_id, Tracer(thread_id=state.thread_id))
        with tracer.span(name, dataset_id=state.dataset_id, messages=state.messages[-1:]):
            return await node_fn(state)

    return wrapped


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
    verified_query_store: VerifiedQueryStore | None = None,
    sql_agent_model_id: str | None = None,
    sql_agent_max_retries: int = 2,
    checkpointer: BaseCheckpointSaver[str] | None = None,
    use_router: bool = False,
    router_model_id: str | None = None,
    tracers: dict[str, Tracer] | None = None,
) -> CompiledStateGraph[OmniState, None, OmniState, OmniState]:
    """Assemble and compile the governed graph for one dataset.

    `verified_query_store` attaches the guarded SQL fallback (Phase 5).
    `checkpointer` attaches durable, interrupt()-based clarification (Phase
    6): an ambiguous match pauses at `clarify` instead of ending the turn.
    `use_router` additionally attaches the intent router ahead of the SQL
    fallback, but only takes effect when both `verified_query_store` and
    `checkpointer` are also given, since the router's own clarification
    branch depends on `clarify` existing. `tracers` (Phase 10) attaches a
    masked-input span to every node when given; omit it and nodes run
    exactly as before, untraced.
    """
    graph: StateGraph[OmniState, None, OmniState, OmniState] = StateGraph(OmniState)

    sql_fallback_enabled = verified_query_store is not None
    durable_clarify_enabled = checkpointer is not None
    router_enabled = use_router and sql_fallback_enabled and durable_clarify_enabled

    clarify_route = "clarify" if durable_clarify_enabled else None
    if router_enabled:
        master_fallback_route: str | None = "router"
    elif sql_fallback_enabled:
        master_fallback_route = "fast_path"
    else:
        master_fallback_route = None

    # langgraph's add_node overloads are typed against its internal _Node
    # protocol family and don't (in this version's stubs) model a bare
    # `async def node(state) -> Command[...]` callable directly, even though
    # that is a supported, documented node shape and works correctly at
    # runtime (exercised end-to-end in tests/integration). Stub gap, not a
    # real type error here.
    graph.add_node(  # type: ignore[call-overload]
        "master",
        _traced(
            "master",
            make_master_node(
                catalog, fallback_route=master_fallback_route, clarify_route=clarify_route
            ),
            tracers,
        ),
    )
    graph.add_node(  # type: ignore[call-overload]
        "semantic_agent",
        _traced(
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
            tracers,
        ),
    )
    graph.add_node(  # type: ignore[call-overload]
        "executor",
        _traced(
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
            tracers,
        ),
    )
    graph.add_node(  # type: ignore[call-overload]
        "narrator", _traced("narrator", make_narrator_node(catalog), tracers)
    )

    if verified_query_store is not None:
        graph.add_node(  # type: ignore[call-overload]
            "fast_path",
            _traced(
                "fast_path",
                make_fast_path_node(
                    dataset_id=dataset_id,
                    engine=engine,
                    verified_query_store=verified_query_store,
                    guardrail_policy=guardrail_policy,
                    semantic_provider=semantic_provider,
                    fallback_route="sql_agent",
                    principal=principal,
                    row_cap=row_cap,
                    timeout_s=timeout_s,
                    gate_config=gate_config,
                ),
                tracers,
            ),
        )
        graph.add_node(  # type: ignore[call-overload]
            "sql_agent",
            _traced(
                "sql_agent",
                make_sql_agent_node(
                    dataset_id=dataset_id,
                    engine=engine,
                    llm=llm,
                    model_id=sql_agent_model_id or model_id,
                    guardrail_policy=guardrail_policy,
                    semantic_provider=semantic_provider,
                    principal=principal,
                    row_cap=row_cap,
                    timeout_s=timeout_s,
                    max_retries=sql_agent_max_retries,
                    gate_config=gate_config,
                ),
                tracers,
            ),
        )

    if durable_clarify_enabled:
        graph.add_node(  # type: ignore[call-overload]
            "clarify",
            _traced(
                "clarify",
                make_clarify_node(
                    catalog=catalog,
                    fallback_route="fast_path" if sql_fallback_enabled else None,
                ),
                tracers,
            ),
        )

    if router_enabled:
        graph.add_node(  # type: ignore[call-overload]
            "router",
            _traced(
                "router",
                make_router_node(
                    catalog=catalog,
                    llm=llm,
                    model_id=router_model_id or model_id,
                    sql_route="fast_path",
                    clarify_route="clarify",
                ),
                tracers,
            ),
        )

    graph.add_edge(START, "master")
    graph.add_edge("narrator", END)

    return graph.compile(checkpointer=checkpointer)
