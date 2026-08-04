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
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from omniagent.adapters.embeddings import FastEmbedProvider
from omniagent.adapters.engine.duckdb import DuckDBEngine
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


def _build_checkpointer(checkpoint_path: str | Path) -> SqliteSaver:
    """A single SQLite-backed checkpointer shared across every dataset's
    graph (thread_id is globally unique regardless of dataset, so one file
    is enough). `SqliteSaver` is a synchronous, single-connection saver -
    fine at this project's scale (a local-first deployment, not a
    multi-process production cluster); `AsyncSqliteSaver` or a
    Postgres-backed saver is the natural upgrade path if that changes,
    matching how the DuckDB engine and Postgres engine already split that
    same scale boundary elsewhere in this codebase.
    """
    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
    return SqliteSaver(conn)


def build_default_datasets(
    *,
    packs_root: str | Path = "packs",
    warehouse_path: str | Path = "data/warehouse/omniagent.duckdb",
    checkpoint_path: str | Path = "data/warehouse/checkpoints.sqlite",
    verified_queries_path: str | Path = "data/warehouse/verified_queries.duckdb",
    model_id: str = DEFAULT_MODEL_ID,
) -> dict[str, DatasetRuntime]:
    """Build every dataset's governed graph against the real Groq API and
    the local DuckDB warehouse. Requires GROQ_API_KEY and a warehouse built
    by scripts/generate_samples.py + scripts/load_warehouse.py."""
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
    checkpointer = _build_checkpointer(checkpoint_path)

    embedder = FastEmbedProvider()
    vector_store = DuckDBVSSStore(verified_queries_path, dim=embedder.dim)
    verified_query_store = DuckDBVerifiedQueryStore(
        vector_store, embedder, min_score=_FAST_PATH_MIN_SCORE
    )

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
        )
        runtimes[dataset_id] = DatasetRuntime(
            dataset_id=dataset_id,
            label=label,
            description=description,
            catalog=catalog,
            graph=graph,
            schema_version=provider.schema_version(dataset_id),
            verified_query_store=verified_query_store,
        )

    return runtimes


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OmniAgent FastAPI service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    import uvicorn

    app = create_app(build_default_datasets())
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
