"""SQL agent: guarded text-to-SQL fallback for questions the semantic layer can't answer.

Reached only when master_node finds no catalog match — the question isn't
about a known metric, so there's nothing deterministic to compile. This is
the one place in the graph where a model writes the actual query, so it is
the most heavily gated path: every candidate runs through the exact same
`GuardrailPolicy` the executor uses (SQL allowlist, row cap, timeout, PII
masking, provenance, LLM budget) before its result is trusted, and a
candidate that fails any gate or the engine itself triggers a bounded
self-correction retry — the model is shown its own error and asked to fix
that specific problem, not to start over blind. Exhausting the retry budget
means abstaining (`error` set, no `goto="narrator"`), never guessing.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from langgraph.graph import END
from langgraph.types import Command

from omniagent.agents.messages import latest_user_message
from omniagent.agents.node_types import GraphNode
from omniagent.kernel.gates import GuardrailPolicy, Unsafe
from omniagent.kernel.models import SqlCandidate
from omniagent.kernel.ports.engine import EngineAdapter, EngineError
from omniagent.kernel.ports.llm import LLMProvider
from omniagent.kernel.ports.semantic import SemanticProvider
from omniagent.kernel.state import OmniState


def make_sql_agent_node(
    *,
    dataset_id: str,
    engine: EngineAdapter,
    llm: LLMProvider,
    model_id: str,
    guardrail_policy: GuardrailPolicy,
    semantic_provider: SemanticProvider | None = None,
    principal: Any = None,
    row_cap: int = 10_000,
    timeout_s: float = 30.0,
    max_retries: int = 2,
    gate_config: dict[str, Any] | None = None,
) -> GraphNode:
    """Bind the engine, model, and gate stack to a guarded SQL-generation node."""

    base_gate_config: dict[str, Any] = {
        "semantic_provider": semantic_provider,
        "max_rows": row_cap,
        "timeout_ms": int(timeout_s * 1000),
        **(gate_config or {}),
    }

    async def sql_agent_node(state: OmniState) -> Command[str]:
        question = latest_user_message(state)
        schema = engine.schema_snapshot(dataset_id)
        dialect = engine.capabilities().dialect

        attempts: list[dict[str, Any]] = []
        model_calls_by_node = dict(state.model_calls_by_node)
        llm_calls = state.llm_calls
        prior_error: str | None = None

        for _ in range(max_retries + 1):
            req: dict[str, Any] = {
                "task": "generate_sql",
                "question": question,
                "schema": schema,
                "dialect": dialect,
            }
            if prior_error is not None:
                req["prior_attempt_sql"] = attempts[-1]["sql"]
                req["prior_error"] = prior_error

            candidate = llm.structured(model_id, req, schema=SqlCandidate)
            llm_calls += 1
            model_calls_by_node["sql_agent"] = model_calls_by_node.get("sql_agent", 0) + 1
            attempts.append(
                {
                    "sql": candidate.sql,
                    "tables_used": candidate.tables_used,
                    "reasoning": candidate.reasoning,
                }
            )

            working = replace(
                state,
                executed_sql=candidate.sql,
                assumptions=list(state.assumptions),
                llm_calls=llm_calls,
                model_calls_by_node=model_calls_by_node,
            )

            try:
                working = await guardrail_policy.apply(working, config=base_gate_config)
            except Unsafe as exc:
                prior_error = exc.reason
                continue

            try:
                result = engine.execute(
                    candidate.sql,
                    principal=principal,
                    timeout_s=timeout_s,
                    row_cap=row_cap,
                )
            except EngineError as exc:
                prior_error = f"{exc.code}: {exc.message}"
                continue

            working.result_set = [
                dict(zip(result.columns, row, strict=True)) for row in result.batches
            ]
            working.result_meta = {
                "row_count": result.row_count,
                "truncated": result.truncated,
                "elapsed_ms": result.elapsed_ms,
            }

            try:
                working = await guardrail_policy.apply(working, config=base_gate_config)
            except Unsafe as exc:
                prior_error = exc.reason
                continue

            return Command(
                goto="narrator",
                update={
                    "executed_sql": candidate.sql,
                    "sql_candidates": attempts,
                    "result_set": working.result_set,
                    "result_meta": working.result_meta,
                    "guarded": working.guarded,
                    "assumptions": working.assumptions,
                    "llm_calls": llm_calls,
                    "model_calls_by_node": model_calls_by_node,
                    "evidence": {
                        "tables": candidate.tables_used,
                        "schema_version": state.schema_version,
                    },
                },
            )

        return Command(
            goto=END,
            update={
                "error": f"Could not produce a safe query after {len(attempts)} attempt(s): {prior_error}",
                "sql_candidates": attempts,
                "llm_calls": llm_calls,
                "model_calls_by_node": model_calls_by_node,
                # Without this, a caller (e.g. eval/redteam.py's is_refused)
                # can't tell a genuine gate refusal on the last attempt apart
                # from an engine/parser error -- `working` still holds
                # whichever attempt's `guarded` a gate call last populated.
                "guarded": working.guarded,
            },
        )

    return sql_agent_node
