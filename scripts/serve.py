#!/usr/bin/env python3
# ruff: noqa: T201
"""Composition root: wire real adapters (Groq, DuckDB, packs) into the
FastAPI service and run it.

Deliberately outside omniagent/ entirely, not just outside omniagent.channels
- the layering contract (.importlinter) keeps omniagent.channels and
omniagent.adapters as parallel top-level layers that must not depend on each
other, so the module that constructs adapters and hands them to channels has
to live outside the package's own layered tree. This is the standard
"composition root" placement for a ports-and-adapters architecture: the
library stays usable without ever needing to know how any one deployment
wires it up.

Usage:
    python scripts/generate_samples.py
    python scripts/load_warehouse.py
    export GROQ_API_KEY=...
    python scripts/serve.py
"""

from __future__ import annotations

import argparse
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from fastapi import FastAPI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from omniagent.adapters.embeddings import FastEmbedProvider
from omniagent.adapters.engine.duckdb import DuckDBEngine
from omniagent.adapters.ledger import DuckDBAnswerLedger
from omniagent.adapters.llm.groq import GroqProvider
from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
from omniagent.adapters.vectors import DuckDBVSSStore
from omniagent.agents.graph import build_governed_graph
from omniagent.channels.service import DatasetRuntime, create_app
from omniagent.kernel.gates import (
    GuardrailPolicy,
    empty_result_gate,
    llm_budget_gate,
    numeric_recompute_gate,
    pii_mask_gate,
    provenance_gate,
    row_cap_gate,
    sql_allowlist_gate,
    timeout_gate,
)
from omniagent.kernel.telemetry import Tracer
from omniagent.kernel.time_resolver import DefaultTimeResolver
from omniagent.memory import DuckDBVerifiedQueryStore

DEFAULT_MODEL_ID = "openai/gpt-oss-20b"

# Empirically calibrated in Phase 5 against real bge-small-en-v1.5 scores: a
# same-shape, different-metric near miss can outscore a genuine paraphrase of
# something else, so the fast path (which skips regeneration entirely on a
# hit) needs a much higher bar than the store's own default noise floor.
# See build_decisions memory decision 11 for the measurements behind this.
_FAST_PATH_MIN_SCORE = 0.92

_ALL_GATES = [
    sql_allowlist_gate,
    row_cap_gate,
    timeout_gate,
    empty_result_gate,
    numeric_recompute_gate,
    pii_mask_gate,
    provenance_gate,
    llm_budget_gate,
]

_DATASETS = {
    "ecommerce": (
        "E-commerce",
        "Orders, returns, and customers for a direct-to-consumer retailer.",
    ),
    "saas": ("SaaS", "Accounts, subscriptions, and invoices for a B2B subscription business."),
}


@asynccontextmanager
async def open_checkpointer(
    checkpoint_path: str | Path,
) -> AsyncIterator[BaseCheckpointSaver[str]]:
    """A single SQLite-backed checkpointer shared across every dataset's
    graph (thread_id is globally unique regardless of dataset, so one file
    is enough).

    `AsyncSqliteSaver` wraps an `aiosqlite.Connection`, whose background
    worker thread must be started and used from the same asyncio event loop
    for its whole lifetime -- opening it here, ahead of `uvicorn.run()`
    starting its own loop with a throwaway `asyncio.run()`, hangs the first
    real request instead of erroring, since the connection's worker thread
    posts results back onto a loop that already stopped running. This
    context manager exists so a composition root only ever opens the
    connection from inside the loop that will actually serve requests
    (FastAPI's `lifespan`, or the single `asyncio.run()` around an MCP
    server's own async entrypoint), not before it.
    """
    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(checkpoint_path))
    try:
        yield AsyncSqliteSaver(conn)
    finally:
        await conn.close()


def build_default_datasets(
    *,
    checkpointer: BaseCheckpointSaver[str],
    packs_root: str | Path = "packs",
    warehouse_path: str | Path = "data/warehouse/omniagent.duckdb",
    verified_queries_path: str | Path = "data/warehouse/verified_queries.duckdb",
    answer_ledger_path: str | Path = "data/warehouse/answer_ledger.duckdb",
    model_id: str = DEFAULT_MODEL_ID,
) -> dict[str, DatasetRuntime]:
    """Build every dataset's governed graph against the real Groq API and
    the local DuckDB warehouse. Requires GROQ_API_KEY and a warehouse built
    by scripts/generate_samples.py + scripts/load_warehouse.py. `checkpointer`
    is built by the caller (see `open_checkpointer`) since a real one needs
    an event loop already running."""
    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError(
            "GROQ_API_KEY is not set. Run scripts/generate_samples.py and "
            "scripts/load_warehouse.py first, then export GROQ_API_KEY."
        )
    if not Path(warehouse_path).exists():
        raise RuntimeError(
            f"Warehouse not found at {warehouse_path}. Run "
            "scripts/generate_samples.py then scripts/load_warehouse.py first."
        )

    llm = GroqProvider()
    provider = NativeYamlProvider(packs_root)
    engine = DuckDBEngine(warehouse_path, read_only=True)
    policy = GuardrailPolicy(gates=_ALL_GATES)
    time_resolver = DefaultTimeResolver()

    embedder = FastEmbedProvider()
    vector_store = DuckDBVSSStore(verified_queries_path, dim=embedder.dim)
    verified_query_store = DuckDBVerifiedQueryStore(
        vector_store, embedder, min_score=_FAST_PATH_MIN_SCORE
    )
    answer_ledger = DuckDBAnswerLedger(answer_ledger_path)

    # One shared registry across every dataset's graph, keyed by thread_id
    # (globally unique regardless of dataset): each turn's node spans land
    # here (see agents/graph.py's `_traced` wrapper), and the answer
    # ledger's `question` field is masked via the same telemetry module
    # before it is ever written to disk.
    tracers: dict[str, Tracer] = {}

    runtimes: dict[str, DatasetRuntime] = {}
    for dataset_id, (label, description) in _DATASETS.items():
        catalog = provider.catalog(dataset_id)
        graph = build_governed_graph(
            dataset_id=dataset_id,
            catalog=catalog,
            semantic_provider=provider,
            engine=engine,
            llm=llm,
            model_id=model_id,
            time_resolver=time_resolver,
            guardrail_policy=policy,
            verified_query_store=verified_query_store,
            checkpointer=checkpointer,
            use_router=True,
            tracers=tracers,
        )
        runtimes[dataset_id] = DatasetRuntime(
            dataset_id=dataset_id,
            label=label,
            description=description,
            catalog=catalog,
            graph=graph,
            schema_version=provider.schema_version(dataset_id),
            verified_query_store=verified_query_store,
            answer_ledger=answer_ledger,
            tracers=tracers,
        )

    return runtimes


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OmniAgent FastAPI service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    import uvicorn

    datasets: dict[str, DatasetRuntime] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with open_checkpointer("data/warehouse/checkpoints.sqlite") as checkpointer:
            datasets.update(build_default_datasets(checkpointer=checkpointer))
            yield

    app = create_app(datasets, lifespan=lifespan)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
