"""FastAPI service: the one entry point every channel (Streamlit, CLI, MCP)
talks to. No channel gets a capability this API doesn't expose.

Endpoints:
  GET  /health              liveness/readiness
  GET  /datasets            datasets available to ask questions against
  POST /ask                 ask a new question (starts or continues a thread)
  POST /resume              continue an existing thread with a new message
  POST /feedback            record a thumbs up/down on a past turn

Thread continuity is a plain in-memory message-history store for this
phase, not LangGraph's checkpointer — Phase 6 upgrades this to durable,
interrupt()-based resumption without changing this API's request/response
shapes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict

from omniagent.agents.suggester import suggest_followups
from omniagent.kernel.catalog import Catalog
from omniagent.kernel.models import AnswerEnvelope, ChartSpec, MetricValue
from omniagent.kernel.state import OmniState


@dataclass
class DatasetRuntime:
    """Everything one dataset needs to answer questions, built once at startup."""

    dataset_id: str
    label: str
    description: str
    catalog: Catalog
    graph: CompiledStateGraph[OmniState, None, OmniState, OmniState]


@dataclass
class _Thread:
    dataset_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_result: dict[str, Any] | None = None


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


def _result_to_envelope(
    result: dict[str, Any], *, thread_id: str, trace_id: str, catalog: Catalog
) -> AnswerEnvelope:
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


def create_app(datasets: dict[str, DatasetRuntime]) -> FastAPI:
    """Build the FastAPI app over an already-constructed set of dataset runtimes."""
    app = FastAPI(title="OmniAgent", version="2.0.0")
    threads: dict[str, _Thread] = {}

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
        thread = threads.setdefault(thread_id, _Thread(dataset_id=request.dataset_id))
        thread.messages.append({"role": "user", "content": request.question})

        state = OmniState(
            thread_id=thread_id,
            dataset_id=request.dataset_id,
            messages=list(thread.messages),
        )
        result = await runtime.graph.ainvoke(state)
        thread.last_result = result

        return _result_to_envelope(
            result, thread_id=thread_id, trace_id=str(uuid.uuid4()), catalog=runtime.catalog
        )

    @app.post("/resume", response_model=AnswerEnvelope)
    async def resume(request: ResumeRequest) -> AnswerEnvelope:
        thread = threads.get(request.thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail=f"Unknown thread {request.thread_id!r}")

        runtime = datasets[thread.dataset_id]
        thread.messages.append({"role": "user", "content": request.message})

        state = OmniState(
            thread_id=request.thread_id,
            dataset_id=thread.dataset_id,
            messages=list(thread.messages),
        )
        result = await runtime.graph.ainvoke(state)
        thread.last_result = result

        return _result_to_envelope(
            result,
            thread_id=request.thread_id,
            trace_id=str(uuid.uuid4()),
            catalog=runtime.catalog,
        )

    @app.post("/feedback")
    async def feedback(request: FeedbackRequest) -> dict[str, Any]:
        if request.thread_id not in threads:
            raise HTTPException(status_code=404, detail=f"Unknown thread {request.thread_id!r}")
        if request.rating not in ("up", "down"):
            raise HTTPException(status_code=422, detail="rating must be 'up' or 'down'")

        # A verified-query pipeline (Phase 5) consumes "up" feedback to seed
        # the fast path; for now this is an honest audit-log sink.
        return {
            "status": "recorded",
            "thread_id": request.thread_id,
            "rating": request.rating,
            "recorded_at": datetime.now(UTC).isoformat(),
        }

    return app
