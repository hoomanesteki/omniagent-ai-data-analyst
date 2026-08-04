"""FastAPI service: the one entry point every channel (Streamlit, CLI, MCP)
talks to. No channel gets a capability this API doesn't expose.

Endpoints:
  GET  /health              liveness/readiness
  GET  /datasets            datasets available to ask questions against
  POST /ask                 ask a new question (starts or continues a thread)
  POST /resume              answer a pending clarification and continue
  POST /feedback            record a thumbs up/down on a past turn

Thread continuity is LangGraph's own checkpointer (passed into each
dataset's compiled graph at the composition root), not an app-level
message-history store: `/ask` and `/resume` both invoke the graph with the
same `thread_id`-scoped config, and the checkpointer handles persisting and
replaying conversation state across calls. `/resume` specifically answers a
pending `interrupt()` via `Command(resume=...)`, continuing the exact graph
run that paused rather than starting a fresh one.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict

from omniagent.agents.suggester import suggest_followups
from omniagent.kernel.catalog import Catalog
from omniagent.kernel.models import AnswerEnvelope, ChartSpec, MetricValue
from omniagent.kernel.ports.identity import Scope
from omniagent.kernel.ports.stores import VerifiedQuery, VerifiedQueryStore
from omniagent.kernel.state import OmniState


@dataclass
class DatasetRuntime:
    """Everything one dataset needs to answer questions, built once at startup."""

    dataset_id: str
    label: str
    description: str
    catalog: Catalog
    graph: CompiledStateGraph[OmniState, None, OmniState, OmniState]
    schema_version: str = ""
    verified_query_store: VerifiedQueryStore | None = None


@dataclass
class _ThreadInfo:
    """The minimum the service needs about a thread outside the checkpointer:
    which dataset it belongs to (so /resume knows which graph to invoke) and
    the last turn's question/answer, so a thumbs-up on /feedback can create
    a verified query without re-deriving them from checkpointed state."""

    dataset_id: str
    last_question: str | None = None
    last_executed_sql: str | None = None
    last_result_set: list[dict[str, Any]] | None = None
    last_matched_metric: str | None = None


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    question: str
    thread_id: str | None = None


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    message: str


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    rating: str  # "up" | "down"
    comment: str | None = None


class DatasetSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    label: str
    description: str
    starter_questions: list[str]


def _starter_questions(catalog: Catalog, limit: int = 4) -> list[str]:
    return [catalog.metrics[name].label for name in catalog.metric_names()[:limit]]


def _result_signature(result_set: list[dict[str, Any]] | None) -> str:
    payload = json.dumps(result_set or [], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _thread_config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


def _result_to_envelope(
    result: dict[str, Any], *, thread_id: str, trace_id: str, catalog: Catalog
) -> AnswerEnvelope:
    interrupts = result.get("__interrupt__")
    if interrupts:
        clarification = interrupts[0].value
        return AnswerEnvelope(
            kind="clarification",
            narration=clarification.get("question"),
            clarification=clarification,
            resumable=True,
            trace_id=trace_id,
            thread_id=thread_id,
        )

    if result.get("needs_human"):
        clarification = result.get("clarification") or {}
        return AnswerEnvelope(
            kind="clarification",
            narration=clarification.get("question"),
            clarification=clarification,
            trace_id=trace_id,
            thread_id=thread_id,
        )

    if result.get("error"):
        return AnswerEnvelope(
            kind="abstention",
            narration=result["error"],
            trace_id=trace_id,
            thread_id=thread_id,
        )

    result_set = result.get("result_set") or []
    metrics = tuple((result.get("semantic_query") or {}).get("metrics", ()))
    values = [
        MetricValue(metric=name, value=result_set[0].get(name))
        for name in metrics
        if len(result_set) == 1 and name in result_set[0]
    ]

    chart_dict = result.get("chart_spec")
    chart = ChartSpec.model_validate(chart_dict) if chart_dict else None

    suggestions = suggest_followups(OmniState(semantic_query=result.get("semantic_query")), catalog)

    return AnswerEnvelope(
        kind="answer",
        headline=result.get("narration"),
        narration=result.get("narration"),
        values=values,
        chart=chart,
        rows=result_set or None,
        executed_sql=result.get("executed_sql"),
        confidence=result.get("confidence"),
        assumptions=list(result.get("assumptions") or []),
        suggestions=suggestions,
        trace_id=trace_id,
        thread_id=thread_id,
    )


def create_app(datasets: dict[str, DatasetRuntime]) -> FastAPI:  # noqa: C901 - five small route handlers as closures, not one branchy function
    """Build the FastAPI app over an already-constructed set of dataset runtimes."""
    app = FastAPI(title="OmniAgent", version="2.0.0")
    threads: dict[str, _ThreadInfo] = {}

    def _record_turn(
        thread_id: str, dataset_id: str, question: str, result: dict[str, Any]
    ) -> None:
        threads[thread_id] = _ThreadInfo(
            dataset_id=dataset_id,
            last_question=question,
            last_executed_sql=result.get("executed_sql"),
            last_result_set=result.get("result_set"),
            last_matched_metric=result.get("matched_metric"),
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/datasets", response_model=list[DatasetSummary])
    async def list_datasets() -> list[DatasetSummary]:
        return [
            DatasetSummary(
                dataset_id=runtime.dataset_id,
                label=runtime.label,
                description=runtime.description,
                starter_questions=_starter_questions(runtime.catalog),
            )
            for runtime in datasets.values()
        ]

    @app.post("/ask", response_model=AnswerEnvelope)
    async def ask(request: AskRequest) -> AnswerEnvelope:
        runtime = datasets.get(request.dataset_id)
        if runtime is None:
            raise HTTPException(status_code=404, detail=f"Unknown dataset {request.dataset_id!r}")

        thread_id = request.thread_id or str(uuid.uuid4())
        config = _thread_config(thread_id)

        state = OmniState(
            thread_id=thread_id,
            dataset_id=request.dataset_id,
            schema_version=runtime.schema_version,
            messages=[{"role": "user", "content": request.question}],
        )
        result = await runtime.graph.ainvoke(state, config)
        _record_turn(thread_id, request.dataset_id, request.question, result)

        return _result_to_envelope(
            result, thread_id=thread_id, trace_id=str(uuid.uuid4()), catalog=runtime.catalog
        )

    @app.post("/resume", response_model=AnswerEnvelope)
    async def resume(request: ResumeRequest) -> AnswerEnvelope:
        info = threads.get(request.thread_id)
        if info is None:
            raise HTTPException(status_code=404, detail=f"Unknown thread {request.thread_id!r}")

        runtime = datasets[info.dataset_id]
        config = _thread_config(request.thread_id)

        state = await runtime.graph.aget_state(config)
        if not state.next:
            raise HTTPException(
                status_code=409,
                detail=f"Thread {request.thread_id!r} has no pending clarification to resume",
            )

        result = await runtime.graph.ainvoke(Command(resume=request.message), config)
        _record_turn(request.thread_id, info.dataset_id, request.message, result)

        return _result_to_envelope(
            result,
            thread_id=request.thread_id,
            trace_id=str(uuid.uuid4()),
            catalog=runtime.catalog,
        )

    @app.post("/feedback")
    async def feedback(request: FeedbackRequest) -> dict[str, Any]:
        info = threads.get(request.thread_id)
        if info is None:
            raise HTTPException(status_code=404, detail=f"Unknown thread {request.thread_id!r}")
        if request.rating not in ("up", "down"):
            raise HTTPException(status_code=422, detail="rating must be 'up' or 'down'")

        runtime = datasets[info.dataset_id]
        verified_query_created = False

        # Only a fallback-path answer (no matched_metric, real executed_sql)
        # is worth caching as a verified query -- a governed answer is
        # already deterministic and fast via the semantic layer, so there
        # is nothing for the fast path to save on.
        if (
            request.rating == "up"
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
                    result_signature=_result_signature(info.last_result_set),
                    status="approved",
                    approved_by="api",
                    created_at=datetime.now(UTC),
                ),
            )
            verified_query_created = True

        return {
            "status": "recorded",
            "thread_id": request.thread_id,
            "rating": request.rating,
            "verified_query_created": verified_query_created,
            "recorded_at": datetime.now(UTC).isoformat(),
        }

    return app
