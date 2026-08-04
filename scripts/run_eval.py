#!/usr/bin/env python3
# ruff: noqa: T201
"""Composition root: run the evaluation harness end to end and print a
scorecard.

Outside omniagent/ for the same reason scripts/serve.py is: this wires
real adapters (DuckDB, optionally Groq) together, which the layering
contract's parallel top layers (omniagent.adapters | omniagent.channels)
forbid any single module inside the package from doing on its own behalf.
omniagent/eval/ itself stays pure logic (goldgen, scorers, redteam), taking
every port as an injected argument.

Usage:
    python scripts/generate_samples.py
    python scripts/load_warehouse.py
    python scripts/run_eval.py
    # with a real model instead of the deterministic stand-in:
    export GROQ_API_KEY=...
    python scripts/run_eval.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from omniagent.adapters.engine.duckdb import DuckDBEngine
from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
from omniagent.agents.graph import build_governed_graph
from omniagent.agents.sql_agent import make_sql_agent_node
from omniagent.eval.goldgen import GoldenItem, generate_golden_set
from omniagent.eval.redteam import CASES as REDTEAM_CASES
from omniagent.eval.redteam import is_refused
from omniagent.eval.scorers import (
    build_scorecard,
    execution_accuracy,
    format_scorecard,
)
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
from omniagent.kernel.models import SqlCandidate
from omniagent.kernel.ports.llm import LLMProvider, ModelCapabilities
from omniagent.kernel.state import OmniState
from omniagent.kernel.time_resolver import DefaultTimeResolver

_DATASETS = ("ecommerce", "saas")

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

_SQL_AGENT_RETRIES = 2


class _RepeatingExtractionLLM(LLMProvider):
    """Stand-in for when no GROQ_API_KEY is set. Every golden item goldgen
    produces is a template phrasing with no time phrase or filter to
    extract, so the one real LLM call every governed question makes
    (semantic_agent's) always resolves the same way regardless of question
    text -- this is exact for these questions, not an approximation, since
    there is genuinely nothing else a real model could correctly extract
    from them either."""

    name = "eval-repeating-extraction"

    def capabilities(self, model_id: str) -> ModelCapabilities:
        raise NotImplementedError("not used by this stand-in")

    def complete(self, model_id: str, req: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("not used by this stand-in")

    def structured(self, model_id: str, req: dict[str, Any], schema: type) -> Any:
        return schema(time_phrase=None, filters=[])

    def stream(self, model_id: str, req: dict[str, Any]) -> Iterator[str]:
        raise NotImplementedError("not used by this stand-in")

    def health(self) -> bool:
        return True


def _build_llm(model_id: str) -> tuple[LLMProvider, str]:
    if os.getenv("GROQ_API_KEY"):
        from omniagent.adapters.llm.groq import GroqProvider

        return GroqProvider(), model_id

    print(
        "GROQ_API_KEY not set: using a deterministic stand-in for the one narrow "
        "extraction call each governed question makes. See _RepeatingExtractionLLM's "
        "docstring for why that's exact, not approximate, for goldgen's own items."
    )
    return _RepeatingExtractionLLM(), "eval-stand-in"


async def _score_golden_item(graph: Any, item: GoldenItem) -> dict[str, float]:
    state = OmniState(
        thread_id=f"eval-{item.item_id}",
        dataset_id=item.dataset_id,
        messages=[{"role": "user", "content": item.question}],
    )
    result = await graph.ainvoke(state)
    return {
        "execution_accuracy": float(
            execution_accuracy(result.get("result_set") or [], item.gold_result)
        ),
        "route_accuracy": float(result.get("route") == "semantic_agent"),
        "metric_match_accuracy": float(result.get("matched_metric") == item.expected_metric),
    }


async def run_golden_evaluation(
    *, dataset_id: str, provider: NativeYamlProvider, engine: DuckDBEngine, model_id: str
) -> tuple[list[GoldenItem], dict[str, list[float]]]:
    """Generate this dataset's golden set and score every item through its
    real governed graph."""
    catalog = provider.catalog(dataset_id)
    llm, resolved_model_id = _build_llm(model_id)
    graph = build_governed_graph(
        dataset_id=dataset_id,
        catalog=catalog,
        semantic_provider=provider,
        engine=engine,
        llm=llm,
        model_id=resolved_model_id,
        time_resolver=DefaultTimeResolver(),
        guardrail_policy=GuardrailPolicy(gates=_ALL_GATES),
    )
    items = generate_golden_set(
        dataset_id=dataset_id, catalog=catalog, semantic_provider=provider, engine=engine
    )

    per_metric: dict[str, list[float]] = {
        "execution_accuracy": [],
        "route_accuracy": [],
        "metric_match_accuracy": [],
    }
    for item in items:
        scores = await _score_golden_item(graph, item)
        for name, value in scores.items():
            per_metric[name].append(value)

    return items, per_metric


async def run_redteam_evaluation(*, engine: DuckDBEngine) -> list[float]:
    """Run every red team case through sql_agent's real gate stack, scripting
    the LLM to attempt the case's induced SQL on every retry."""
    scores: list[float] = []
    for case in REDTEAM_CASES:
        from tests.fakes.llm import ScriptedLLM  # eval-only dependency on the test fake

        llm = ScriptedLLM(
            [SqlCandidate(sql=case.induced_sql, tables_used=[])] * (_SQL_AGENT_RETRIES + 1)
        )
        node = make_sql_agent_node(
            dataset_id="ecommerce",
            engine=engine,
            llm=llm,
            model_id="redteam-stand-in",
            guardrail_policy=GuardrailPolicy(gates=_ALL_GATES),
            max_retries=_SQL_AGENT_RETRIES,
        )
        state = OmniState(
            thread_id=f"redteam-{case.case_id}",
            dataset_id="ecommerce",
            messages=[{"role": "user", "content": case.question}],
        )
        cmd = await node(state)
        scores.append(float(is_refused(cmd.update or {})))
    return scores


async def main_async(*, packs_root: str | Path, warehouse_path: str | Path, model_id: str) -> None:
    if not Path(warehouse_path).exists():
        raise RuntimeError(
            f"Warehouse not found at {warehouse_path}. Run scripts/generate_samples.py "
            "then scripts/load_warehouse.py first."
        )

    provider = NativeYamlProvider(packs_root)
    engine = DuckDBEngine(warehouse_path, read_only=True)

    all_metrics: dict[str, list[float]] = {
        "execution_accuracy": [],
        "route_accuracy": [],
        "metric_match_accuracy": [],
    }
    total_items = 0
    for dataset_id in _DATASETS:
        items, per_metric = await run_golden_evaluation(
            dataset_id=dataset_id, provider=provider, engine=engine, model_id=model_id
        )
        total_items += len(items)
        print(f"{dataset_id}: {len(items)} golden items")
        for name, scores in per_metric.items():
            all_metrics[name].extend(scores)

    redteam_scores = await run_redteam_evaluation(engine=engine)
    all_metrics["redteam_refusal_rate"] = redteam_scores

    print()
    print(f"Golden set: {total_items} items across {len(_DATASETS)} datasets")
    print(f"Red team: {len(redteam_scores)} cases")
    print()
    print(format_scorecard(build_scorecard(all_metrics)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packs", type=Path, default=Path("packs"))
    parser.add_argument("--warehouse", type=Path, default=Path("data/warehouse/omniagent.duckdb"))
    parser.add_argument("--model-id", default="openai/gpt-oss-20b")
    args = parser.parse_args()

    asyncio.run(
        main_async(packs_root=args.packs, warehouse_path=args.warehouse, model_id=args.model_id)
    )


if __name__ == "__main__":
    main()
