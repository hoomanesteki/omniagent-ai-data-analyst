"""Executor: compile the semantic query, guard, execute, guard again.

The compiled SQL is deterministic (no LLM in this path), so there is no
self-correction loop here — a compile failure is a bug in the pack or the
compiler, not something a retry fixes. The gate stack runs twice: once
before the engine call (seeds timeout_gate's clock and rejects unsafe SQL
before it's ever sent to the engine — the engine's own read-only connection
is the primary wall, this is defense in depth) and once after (checks
elapsed time, row cap, PII, provenance, and abstention against the actual
result).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from langgraph.graph import END
from langgraph.types import Command

from omniagent.agents.node_types import GraphNode
from omniagent.agents.query_codec import query_from_dict
from omniagent.kernel.gates import GuardrailPolicy, Unsafe
from omniagent.kernel.ports.engine import EngineAdapter, EngineError
from omniagent.kernel.ports.semantic import SemanticProvider
from omniagent.kernel.state import OmniState


def make_executor_node(
    *,
    dataset_id: str,
    semantic_provider: SemanticProvider,
    engine: EngineAdapter,
    guardrail_policy: GuardrailPolicy,
    principal: Any = None,
    row_cap: int = 10_000,
    timeout_s: float = 30.0,
    gate_config: dict[str, Any] | None = None,
) -> GraphNode:
    """Bind the semantic provider, engine, and gate stack to a node function."""

    base_gate_config: dict[str, Any] = {
        "max_rows": row_cap,
        "timeout_ms": int(timeout_s * 1000),
        "semantic_provider": semantic_provider,
        **(gate_config or {}),
    }

    async def executor_node(state: OmniState) -> Command[str]:
        if state.semantic_query is None:
            return Command(goto=END, update={"error": "executor reached with no semantic_query"})
        query = query_from_dict(state.semantic_query)
        compiled = semantic_provider.compile(dataset_id, query)

        # A fresh assumptions list, decoupled from the caller's — gates
        # mutate it in place, and the caller's list must not be aliased
        # into that mutation (it's LangGraph-tracked state, not ours to
        # touch outside a returned update).
        working = replace(state, executed_sql=compiled.sql, assumptions=list(state.assumptions))

        try:
            working = await guardrail_policy.apply(working, config=base_gate_config)
        except Unsafe as exc:
            return Command(
                goto=END,
                update={
                    "error": exc.reason,
                    "executed_sql": compiled.sql,
                    "guarded": working.guarded,
                },
            )

        try:
            result = engine.execute(
                compiled.sql,
                params=compiled.provenance["params"],
                principal=principal,
                timeout_s=timeout_s,
                row_cap=row_cap,
            )
        except EngineError as exc:
            return Command(
                goto=END,
                update={"error": f"{exc.code}: {exc.message}", "executed_sql": compiled.sql},
            )

        working.result_set = [dict(zip(result.columns, row, strict=True)) for row in result.batches]
        working.result_meta = {
            "row_count": result.row_count,
            "truncated": result.truncated,
            "elapsed_ms": result.elapsed_ms,
        }

        try:
            working = await guardrail_policy.apply(working, config=base_gate_config)
        except Unsafe as exc:
            return Command(
                goto=END,
                update={
                    "error": exc.reason,
                    "executed_sql": compiled.sql,
                    "result_meta": working.result_meta,
                    "guarded": working.guarded,
                },
            )

        new_assumptions = working.assumptions[len(state.assumptions) :]

        return Command(
            goto="narrator",
            update={
                "executed_sql": compiled.sql,
                "result_set": working.result_set,
                "result_meta": working.result_meta,
                "guarded": working.guarded,
                "assumptions": new_assumptions,
                "evidence": {
                    "tables": compiled.provenance.get("tables", []),
                    "schema_version": compiled.provenance.get("schema_version"),
                },
            },
        )

    return executor_node
