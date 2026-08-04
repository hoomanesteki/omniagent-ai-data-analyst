"""Governed graph: master -> semantic_agent -> executor -> narrator,
with an optional guarded fallback: master -> fast_path -> sql_agent -> narrator.

This wires the deterministic-first path: a question either matches the
catalog deterministically and flows through to a governed, gate-checked,
narrated answer, or (with `verified_query_store` configured) falls through
to the guarded SQL path — a cache-first check against previously verified
queries, then live model-generated SQL, both behind the same gate stack the
governed path uses. Without a fallback configured, an unmatched question
still terminates in master's plain clarification. A model-based router
(Phase 6) attaches ahead of this same graph later without changing this
wiring.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from omniagent.agents.executor import make_executor_node
from omniagent.agents.fast_path import make_fast_path_node
from omniagent.agents.master import make_master_node
from omniagent.agents.narrator import make_narrator_node
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
) -> CompiledStateGraph[OmniState, None, OmniState, OmniState]:
    """Assemble and compile the governed graph for one dataset.

    The guarded SQL fallback (fast_path -> sql_agent) attaches only when
    `verified_query_store` is given — without one, an unmatched question
    still ends in master's plain clarification, exactly as before Phase 5.
    """
    graph: StateGraph[OmniState, None, OmniState, OmniState] = StateGraph(OmniState)

    # langgraph's add_node overloads are typed against its internal _Node
    # protocol family and don't (in this version's stubs) model a bare
    # `async def node(state) -> Command[...]` callable directly, even though
    # that is a supported, documented node shape and works correctly at
    # runtime (exercised end-to-end in tests/integration). Stub gap, not a
    # real type error here.
    graph.add_node(  # type: ignore[call-overload]
        "master",
        make_master_node(
            catalog, fallback_route="fast_path" if verified_query_store is not None else None
        ),
    )
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

    if verified_query_store is not None:
        graph.add_node(  # type: ignore[call-overload]
            "fast_path",
            make_fast_path_node(
                dataset_id=dataset_id,
                engine=engine,
                verified_query_store=verified_query_store,
                guardrail_policy=guardrail_policy,
                fallback_route="sql_agent",
                principal=principal,
                row_cap=row_cap,
                timeout_s=timeout_s,
                gate_config=gate_config,
            ),
        )
        graph.add_node(  # type: ignore[call-overload]
            "sql_agent",
            make_sql_agent_node(
                dataset_id=dataset_id,
                engine=engine,
                llm=llm,
                model_id=sql_agent_model_id or model_id,
                guardrail_policy=guardrail_policy,
                principal=principal,
                row_cap=row_cap,
                timeout_s=timeout_s,
                max_retries=sql_agent_max_retries,
                gate_config=gate_config,
            ),
        )

    graph.add_edge(START, "master")
    graph.add_edge("narrator", END)

    return graph.compile()
