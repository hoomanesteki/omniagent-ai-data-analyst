"""MCP server: the same governed answer engine exposed to MCP clients
(other agents, IDE assistants) instead of a browser or a REST caller.

No channel gets a capability another channel lacks: the tools here are a
1:1 mirror of `channels/service.py`'s routes (list datasets, ask, resume,
feedback) built over the exact same `DatasetRuntime` objects, the same
gate stack, and the shared `record_turn`/`result_to_envelope` helpers --
not a second implementation that could quietly drift from the REST one.
There is deliberately no raw-SQL tool: an MCP client gets the same
governed, gated path a human using the UI gets, nothing more direct.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command
from mcp.server.mcpserver import MCPServer

from omniagent.channels.service import (
    DatasetRuntime,
    ThreadInfo,
    record_turn,
    result_signature,
    result_to_envelope,
    starter_questions,
    thread_config,
)
from omniagent.kernel.ports.identity import Scope
from omniagent.kernel.ports.stores import VerifiedQuery
from omniagent.kernel.state import OmniState


def build_mcp_server(  # noqa: C901 - four small tool handlers as closures, not one branchy function
    datasets: dict[str, DatasetRuntime], *, name: str = "omniagent"
) -> MCPServer:
    """Build an MCP server over an already-constructed set of dataset
    runtimes -- the same runtimes `create_app()` would take, so a
    deployment can run both channels side by side against identical state
    if it wants to (they do not currently share a `threads` dict; each
    channel that drives one is only ever tracking its own callers)."""
    server = MCPServer(
        name=name,
        instructions=(
            "Ask governed questions about the available datasets. Every "
            "answer is produced by a deterministic semantic layer or a "
            "guarded, gate-checked SQL fallback -- there is no tool here "
            "for running arbitrary SQL."
        ),
    )
    threads: dict[str, ThreadInfo] = {}

    @server.tool(description="List the datasets available to ask questions against.")
    async def list_datasets() -> list[dict[str, Any]]:
        return [
            {
                "dataset_id": runtime.dataset_id,
                "label": runtime.label,
                "description": runtime.description,
                "starter_questions": starter_questions(runtime.catalog),
            }
            for runtime in datasets.values()
        ]

    @server.tool(
        description=(
            "Ask a question about one dataset. Starts a new thread when "
            "thread_id is omitted, or continues an existing one when "
            "supplied -- the same thread_id also lets a later `resume` or "
            "`feedback` call refer back to this turn."
        )
    )
    async def ask(dataset_id: str, question: str, thread_id: str | None = None) -> dict[str, Any]:
        runtime = datasets.get(dataset_id)
        if runtime is None:
            raise ValueError(f"Unknown dataset {dataset_id!r}")

        resolved_thread_id = thread_id or str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        config = thread_config(resolved_thread_id)

        state = OmniState(
            thread_id=resolved_thread_id,
            dataset_id=dataset_id,
            schema_version=runtime.schema_version,
            messages=[{"role": "user", "content": question}],
        )
        result = await runtime.graph.ainvoke(state, config)
        record_turn(runtime, threads, resolved_thread_id, trace_id, question, result)

        envelope = result_to_envelope(
            result, thread_id=resolved_thread_id, trace_id=trace_id, catalog=runtime.catalog
        )
        return envelope.model_dump()

    @server.tool(
        description=(
            "Answer a pending clarification for a thread returned by `ask` "
            "with resumable=true. Fails if the thread has nothing pending."
        )
    )
    async def resume(thread_id: str, message: str) -> dict[str, Any]:
        info = threads.get(thread_id)
        if info is None:
            raise ValueError(f"Unknown thread {thread_id!r}")

        runtime = datasets[info.dataset_id]
        trace_id = str(uuid.uuid4())
        config = thread_config(thread_id)

        state = await runtime.graph.aget_state(config)
        if not state.next:
            raise ValueError(f"Thread {thread_id!r} has no pending clarification to resume")

        result = await runtime.graph.ainvoke(Command(resume=message), config)
        record_turn(runtime, threads, thread_id, trace_id, message, result)

        return result_to_envelope(
            result, thread_id=thread_id, trace_id=trace_id, catalog=runtime.catalog
        ).model_dump()

    @server.tool(
        description=(
            "Record a thumbs up/down on a thread's last answer. A thumbs "
            "up on a guarded-fallback answer (one with no matched semantic "
            "metric) saves it as a verified query for the fast path."
        )
    )
    async def feedback(thread_id: str, rating: str, comment: str | None = None) -> dict[str, Any]:
        info = threads.get(thread_id)
        if info is None:
            raise ValueError(f"Unknown thread {thread_id!r}")
        if rating not in ("up", "down"):
            raise ValueError("rating must be 'up' or 'down'")

        runtime = datasets[info.dataset_id]
        verified_query_created = False

        if (
            rating == "up"
            and runtime.verified_query_store is not None
            and info.last_matched_metric is None
            and info.last_executed_sql
            and info.last_question
        ):
            scope = Scope(
                tenant="local", dataset=info.dataset_id, schema_version=runtime.schema_version
            )
            runtime.verified_query_store.add(
                scope,
                VerifiedQuery(
                    question=info.last_question,
                    artifact=info.last_executed_sql,
                    result_signature=result_signature(info.last_result_set),
                    status="approved",
                    approved_by="mcp",
                    created_at=datetime.now(UTC),
                ),
            )
            verified_query_created = True

        return {
            "status": "recorded",
            "thread_id": thread_id,
            "rating": rating,
            "verified_query_created": verified_query_created,
            "recorded_at": datetime.now(UTC).isoformat(),
        }

    return server
