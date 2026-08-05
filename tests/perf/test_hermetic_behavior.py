"""Hermetic performance/behavior tests: no real network, no real LLM, no
real subprocess -- just call-count spies, subprocess spies, and generous
wall-clock ceilings loose enough to never flake on a slow CI runner but
tight enough to catch a genuine regression (an accidental extra call, a
runaway retry loop, an accidental blocking I/O or subprocess spawn).

A cold first call through a freshly-compiled LangGraph graph carries real,
one-time setup overhead unrelated to this project's own code (observed
~200ms locally); thresholds here are set well above that, not tuned to
the noise floor of one machine.
"""

import asyncio
import subprocess
import time

import pytest

from omniagent.agents.sql_agent import make_sql_agent_node
from omniagent.kernel.catalog import Catalog, MetricInfo
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
from omniagent.kernel.models import SemanticExtraction, SqlCandidate
from omniagent.kernel.state import OmniState
from tests.fakes.llm import ScriptedLLM

ALL_GATES = [
    sql_allowlist_gate,
    row_cap_gate,
    timeout_gate,
    empty_result_gate,
    numeric_recompute_gate,
    pii_mask_gate,
    provenance_gate,
    llm_budget_gate,
]


@pytest.mark.perf
class TestGovernedPathBudget:
    def test_exactly_one_llm_call_and_completes_within_budget(self, ecommerce_warehouse):
        from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
        from omniagent.agents.graph import build_governed_graph
        from omniagent.kernel.time_resolver import DefaultTimeResolver

        provider = NativeYamlProvider("packs")
        catalog = provider.catalog("ecommerce")
        llm = ScriptedLLM([SemanticExtraction(time_phrase=None, filters=[])])
        graph = build_governed_graph(
            dataset_id="ecommerce",
            catalog=catalog,
            semantic_provider=provider,
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="m",
            time_resolver=DefaultTimeResolver(),
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
        )

        started = time.monotonic()
        result = asyncio.run(
            graph.ainvoke(
                OmniState(
                    thread_id="t1",
                    dataset_id="ecommerce",
                    messages=[{"role": "user", "content": "gross revenue"}],
                )
            )
        )
        elapsed_s = time.monotonic() - started

        llm.assert_call_count(1)
        assert result["narration"] == "Gross revenue was $225.00."
        # Generous for the same reason as TestCatalogMatchScales below: this
        # must survive CPU contention under `-n auto` parallel execution,
        # not benchmark precisely -- an accidental blocking sleep or retry
        # loop would still blow past 10s by a wide margin.
        assert elapsed_s < 10.0, f"governed path took {elapsed_s:.2f}s, expected well under 10s"


@pytest.mark.perf
class TestNoSubprocessSpawned:
    def test_governed_path_spawns_zero_subprocesses(self, ecommerce_warehouse, monkeypatch):
        """The whole point of an in-process semantic provider and a local
        DuckDB engine is no subprocess anywhere in the governed path -- a
        stray subprocess would mean a silent dependency on an external
        binary this project never asked for."""
        from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
        from omniagent.agents.graph import build_governed_graph
        from omniagent.kernel.time_resolver import DefaultTimeResolver

        spawned: list[object] = []
        original_popen = subprocess.Popen

        def spy_popen(*args, **kwargs):
            spawned.append(args)
            return original_popen(*args, **kwargs)

        monkeypatch.setattr(subprocess, "Popen", spy_popen)

        provider = NativeYamlProvider("packs")
        catalog = provider.catalog("ecommerce")
        llm = ScriptedLLM([SemanticExtraction(time_phrase=None, filters=[])])
        graph = build_governed_graph(
            dataset_id="ecommerce",
            catalog=catalog,
            semantic_provider=provider,
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="m",
            time_resolver=DefaultTimeResolver(),
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
        )

        asyncio.run(
            graph.ainvoke(
                OmniState(
                    thread_id="t1",
                    dataset_id="ecommerce",
                    messages=[{"role": "user", "content": "gross revenue by channel"}],
                )
            )
        )

        assert spawned == []


@pytest.mark.perf
class TestSqlAgentRetryLoopIsBounded:
    def test_retry_loop_never_exceeds_max_retries_plus_one_calls(self, ecommerce_warehouse):
        """A pathological LLM that always returns unsafe SQL must still
        only ever cost `max_retries + 1` calls, never more -- the bound
        that keeps a red-team attempt (or a genuinely broken model) from
        burning unbounded time or tokens."""
        max_retries = 5
        llm = ScriptedLLM(
            [SqlCandidate(sql="DROP TABLE ecommerce_orders", tables_used=[])] * (max_retries + 1)
        )
        node = make_sql_agent_node(
            dataset_id="ecommerce",
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="m",
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            max_retries=max_retries,
        )
        state = OmniState(
            thread_id="t1",
            dataset_id="ecommerce",
            messages=[{"role": "user", "content": "drop the orders table"}],
        )

        cmd = asyncio.run(node(state))

        assert cmd.update["error"] is not None
        llm.assert_call_count(max_retries + 1)


@pytest.mark.perf
class TestCatalogMatchScales:
    def test_match_stays_fast_against_a_large_catalog(self):
        """Deterministic phrase matching must not degrade badly as the
        catalog grows -- a real dataset could plausibly have a few hundred
        metrics across many packs' worth of models."""
        metrics = {
            f"metric_{i}": MetricInfo(
                name=f"metric_{i}", label=f"Metric {i}", synonyms=(f"synonym phrase {i}",)
            )
            for i in range(300)
        }
        catalog = Catalog(dataset_id="large", metrics=metrics)

        # CPU time, not wall clock: under `-n auto` parallel execution a
        # worker can go unscheduled for seconds at a time under contention
        # from unrelated tests with no CPU actually spent on this test's own
        # work. process_time() only counts time this process actually ran,
        # so it stays a meaningful signal for an algorithmic blowup (e.g. an
        # accidental O(n^3)) regardless of how busy the machine is.
        #
        # The threshold below is deliberately generous, not a benchmark: the
        # real measured cost on an idle machine is ~0.15s (measured
        # 2026-08-04), so 5.0s is a >30x margin. Even that margin has been
        # observed to occasionally trip on a genuinely oversubscribed CI
        # runner, since heavy contention can distort CPU-time accounting
        # itself (cache thrashing, frequency scaling), not just wall-clock
        # scheduling delays -- a real O(n^2)/O(n^3) regression at this input
        # size would blow past 5s by a wide margin regardless.
        started = time.process_time()
        for _ in range(50):
            catalog.match("what is synonym phrase 150")
        cpu_s = time.process_time() - started

        assert cpu_s < 5.0, f"50 matches against 300 metrics used {cpu_s:.2f}s of CPU time"


@pytest.mark.perf
# See tests/contract/test_verified_queries.py's pytestmark comment: shared
# xdist_group so concurrent workers don't race to load the real embedding
# model at once. Only this class needs it -- the others in this module
# never touch FastEmbedProvider.
@pytest.mark.xdist_group(name="fastembed")
class TestFastPathHitMakesZeroLlmCalls:
    def test_verified_query_hit_never_calls_the_model(self, ecommerce_warehouse):
        from datetime import UTC, datetime

        from omniagent.adapters.embeddings import FastEmbedProvider
        from omniagent.adapters.vectors import DuckDBVSSStore
        from omniagent.agents.fast_path import make_fast_path_node
        from omniagent.kernel.ports.identity import Scope
        from omniagent.kernel.ports.stores import VerifiedQuery
        from omniagent.memory.verified_queries import DuckDBVerifiedQueryStore

        embedder = FastEmbedProvider()
        with DuckDBVSSStore(dim=embedder.dim) as vstore:
            store = DuckDBVerifiedQueryStore(vstore, embedder)
            scope = Scope(tenant="local", dataset="ecommerce", schema_version="")
            store.add(
                scope,
                VerifiedQuery(
                    question="how many orders are completed",
                    artifact="SELECT COUNT(*) AS n FROM ecommerce_orders WHERE order_status = 'completed'",
                    result_signature="sig",
                    status="approved",
                    approved_by="test",
                    created_at=datetime.now(UTC),
                ),
            )
            node = make_fast_path_node(
                dataset_id="ecommerce",
                engine=ecommerce_warehouse,
                verified_query_store=store,
                guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            )
            state = OmniState(
                thread_id="t1",
                dataset_id="ecommerce",
                messages=[{"role": "user", "content": "how many orders are completed"}],
            )

            cmd = asyncio.run(node(state))

            assert cmd.goto == "narrator"
            assert cmd.update["result_set"] == [{"n": 3}]
            # No LLM object was even constructed for this node -- the
            # strongest possible "zero calls" guarantee, since there is
            # nothing to call in the first place.
