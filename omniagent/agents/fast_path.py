"""Fast path: serve a previously verified query without a model call.

Reached only when master_node finds no deterministic catalog match — before
falling back to sql_agent's (more expensive, riskier) live generation, check
whether a close-enough question has already been asked, approved, and
verified. A hit still re-executes the stored artifact through the full gate
stack against current data (verified queries cache the *query*, not a
point-in-time *result*), so a fast-path answer is exactly as governed as a
freshly generated one — it just skips the LLM call.

`DuckDBVerifiedQueryStore`'s own `min_score` floor only rejects obviously
unrelated questions (~0.5 by default); it is not precise enough on its own
to gate "skip generation entirely" — see verified_queries.py's docstring: a
same-shape, different-metric near miss can outscore a genuine paraphrase of
something else. Construct this node's store with a much stricter `min_score`
(e.g. 0.92) so only a near-exact repeat of a previously verified question
counts as a hit; anything less confident falls through to sql_agent, which
generates and gates a fresh candidate rather than trusting a guess.

A hit that fails to execute (schema drift, a gate violation) is not a dead
end — it falls through to sql_agent exactly like a cache miss, since the
verified artifact may simply be stale.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from langgraph.types import Command

from omniagent.agents.messages import latest_user_message
from omniagent.agents.node_types import GraphNode
from omniagent.kernel.gates import GuardrailPolicy, Unsafe
from omniagent.kernel.ports.engine import EngineAdapter, EngineError
from omniagent.kernel.ports.identity import Scope
from omniagent.kernel.ports.stores import VerifiedQueryStore
from omniagent.kernel.state import OmniState


def make_fast_path_node(
    *,
    dataset_id: str,
    engine: EngineAdapter,
    verified_query_store: VerifiedQueryStore,
    guardrail_policy: GuardrailPolicy,
    fallback_route: str = "sql_agent",
    principal: Any = None,
    row_cap: int = 10_000,
    timeout_s: float = 30.0,
    gate_config: dict[str, Any] | None = None,
) -> GraphNode:
    """Bind the verified-query store and engine to a cache-first node."""

    base_gate_config: dict[str, Any] = {
        "max_rows": row_cap,
        "timeout_ms": int(timeout_s * 1000),
        **(gate_config or {}),
    }

    async def fast_path_node(state: OmniState) -> Command[str]:
        question = latest_user_message(state)
        scope = Scope(
            tenant=state.principal.get("tenant_id", "local"),
            dataset=dataset_id,
            schema_version=state.schema_version,
        )

        hits = verified_query_store.retrieve(scope, question, k=1, min_status="approved")
        if not hits or not isinstance(hits[0].artifact, str):
            return Command(goto=fallback_route, update={})

        sql = hits[0].artifact
        working = replace(state, executed_sql=sql, assumptions=list(state.assumptions))

        try:
            working = await guardrail_policy.apply(working, config=base_gate_config)
        except Unsafe:
            return Command(goto=fallback_route, update={})

        try:
            result = engine.execute(sql, principal=principal, timeout_s=timeout_s, row_cap=row_cap)
        except EngineError:
            return Command(goto=fallback_route, update={})

        working.result_set = [dict(zip(result.columns, row, strict=True)) for row in result.batches]
        working.result_meta = {
            "row_count": result.row_count,
            "truncated": result.truncated,
            "elapsed_ms": result.elapsed_ms,
        }

        try:
            working = await guardrail_policy.apply(working, config=base_gate_config)
        except Unsafe:
            return Command(goto=fallback_route, update={})

        return Command(
            goto="narrator",
            update={
                "executed_sql": sql,
                "result_set": working.result_set,
                "result_meta": working.result_meta,
                "guarded": working.guarded,
                "assumptions": working.assumptions,
                "evidence": {
                    "tables": [],
                    "schema_version": scope.schema_version,
                    "verified_query_hit": True,
                },
            },
        )

    return fast_path_node
