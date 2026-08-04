"""Integration tests: the full graph with the guarded SQL fallback wired in.

Verifies the roadmap's Phase 5 "Done When" criteria end to end: an
out-of-scope question produces a valid, gate-checked answer via sql_agent;
a thumbs-up-equivalent verified query serves the same question again with
zero model calls; and the governed (catalog-matched) path is completely
unaffected by the fallback being configured.

Uses a purpose-built warehouse with one extra table
(`ecommerce_shipping_carriers`) that has no corresponding pack model at
all, so a question about it is guaranteed not to catalog-match — unlike
reusing an existing pack-modeled table, which risks an incidental
deterministic match to some real metric/dimension.
"""

from datetime import UTC, datetime

import duckdb
import pytest

from omniagent.adapters.embeddings import FastEmbedProvider
from omniagent.adapters.engine.duckdb import DuckDBEngine
from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
from omniagent.adapters.vectors import DuckDBVSSStore
from omniagent.agents.graph import build_governed_graph
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
from omniagent.kernel.ports.identity import Scope
from omniagent.kernel.ports.stores import VerifiedQuery
from omniagent.kernel.state import OmniState
from omniagent.kernel.time_resolver import DefaultTimeResolver
from omniagent.memory.verified_queries import DuckDBVerifiedQueryStore
from tests.fakes.llm import ScriptedLLM

NOW = datetime(2026, 8, 3)

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

_CARRIER_SQL = (
    "SELECT carrier_name, on_time_rate FROM ecommerce_shipping_carriers ORDER BY on_time_rate DESC"
)
_CARRIER_RESULT = [
    {"carrier_name": "FastShip", "on_time_rate": 0.95},
    {"carrier_name": "SlowShip", "on_time_rate": 0.80},
]
_QUESTION = "which shipping carrier has the best on time rate"


@pytest.fixture
def provider():
    return NativeYamlProvider("packs")


@pytest.fixture
def warehouse_with_unmodeled_table(tmp_path):
    """The same tables as the shared ecommerce warehouse, plus one extra
    table with no pack model at all, so a question about it can never
    catalog-match (built standalone since the shared fixture's engine is
    read-only and can't have a table added to it after the fact)."""
    db_path = tmp_path / "fallback_warehouse.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE ecommerce_customers (
            customer_id VARCHAR, country VARCHAR, region VARCHAR,
            customer_segment VARCHAR, marketing_channel VARCHAR,
            signup_date DATE, email VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO ecommerce_customers VALUES
        ('C1', 'US', 'West', 'consumer', 'organic', '2026-01-15', 'c1@example.com'),
        ('C2', 'US', 'East', 'business', 'paid_search', '2026-02-01', 'c2@example.com'),
        ('C3', 'UK', 'London', 'consumer', 'referral', '2026-04-01', 'c3@example.com')
    """)
    conn.execute("""
        CREATE TABLE ecommerce_orders (
            order_id VARCHAR, customer_id VARCHAR, order_date DATE,
            order_status VARCHAR, channel VARCHAR, payment_method VARCHAR,
            shipping_country VARCHAR, discount_code VARCHAR, order_total DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO ecommerce_orders VALUES
        ('O1', 'C1', '2026-04-15', 'completed', 'web', 'card', 'US', NULL, 100.0),
        ('O2', 'C1', '2026-05-10', 'completed', 'web', 'card', 'US', NULL, 50.0),
        ('O3', 'C2', '2026-05-01', 'cancelled', 'web', 'card', 'US', NULL, 200.0),
        ('O4', 'C3', '2026-04-05', 'completed', 'mobile_app', 'card', 'UK', NULL, 75.0)
    """)
    conn.execute("""
        CREATE TABLE ecommerce_order_items (
            item_id VARCHAR, order_id VARCHAR, product_id VARCHAR,
            quantity INTEGER, unit_price DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO ecommerce_order_items VALUES
        ('I1', 'O1', 'P1', 2, 50.0), ('I2', 'O2', 'P1', 1, 50.0),
        ('I3', 'O3', 'P2', 5, 40.0), ('I4', 'O4', 'P1', 3, 25.0)
    """)
    conn.execute("""
        CREATE TABLE ecommerce_returns (
            return_id VARCHAR, order_id VARCHAR, return_reason VARCHAR,
            return_status VARCHAR, return_date DATE, refund_amount DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO ecommerce_returns VALUES
        ('R1', 'O1', 'defective', 'approved', '2026-04-25', 20.0),
        ('R2', 'O2', 'wrong_size', 'pending', '2026-05-15', 10.0)
    """)
    conn.execute("""
        CREATE TABLE ecommerce_shipping_carriers (
            carrier_id VARCHAR, carrier_name VARCHAR, on_time_rate DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO ecommerce_shipping_carriers VALUES
        ('C1', 'FastShip', 0.95), ('C2', 'SlowShip', 0.80)
    """)
    conn.close()

    engine = DuckDBEngine(db_path, read_only=False)
    yield engine
    engine.close()


@pytest.fixture(scope="module")
def embedder():
    return FastEmbedProvider()


@pytest.fixture
def verified_store(embedder):
    with DuckDBVSSStore(dim=embedder.dim) as vstore:
        yield DuckDBVerifiedQueryStore(vstore, embedder, min_score=0.9)


def _build_graph(provider, engine, script, verified_store, model_id="test-model"):
    catalog = provider.catalog("ecommerce")
    llm = ScriptedLLM(script)
    graph = build_governed_graph(
        dataset_id="ecommerce",
        catalog=catalog,
        semantic_provider=provider,
        engine=engine,
        llm=llm,
        model_id=model_id,
        time_resolver=DefaultTimeResolver(),
        guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
        now_fn=lambda: NOW,
        verified_query_store=verified_store,
    )
    return graph, llm


class TestGuardedFallbackAcceptance:
    """Roadmap's literal Phase 5 'Done When' criteria."""

    @pytest.mark.integration
    async def test_out_of_scope_question_produces_a_valid_answer(
        self, provider, warehouse_with_unmodeled_table, verified_store
    ):
        graph, llm = _build_graph(
            provider,
            warehouse_with_unmodeled_table,
            [SqlCandidate(sql=_CARRIER_SQL, tables_used=["ecommerce_shipping_carriers"])],
            verified_store,
        )
        initial = OmniState(
            thread_id="t1",
            dataset_id="ecommerce",
            schema_version="v1",
            messages=[{"role": "user", "content": _QUESTION}],
        )

        result = await graph.ainvoke(initial)

        assert (
            result["route"] == "fast_path"
        )  # master's first hop; fast_path misses and falls through
        assert result.get("error") is None
        assert result["result_set"] == _CARRIER_RESULT
        llm.assert_call_count(1)

    @pytest.mark.integration
    async def test_broken_first_candidate_self_corrects_within_budget(
        self, provider, warehouse_with_unmodeled_table, verified_store
    ):
        graph, llm = _build_graph(
            provider,
            warehouse_with_unmodeled_table,
            [
                SqlCandidate(sql="DROP TABLE ecommerce_shipping_carriers", tables_used=[]),
                SqlCandidate(sql=_CARRIER_SQL, tables_used=["ecommerce_shipping_carriers"]),
            ],
            verified_store,
        )
        initial = OmniState(
            thread_id="t1",
            dataset_id="ecommerce",
            schema_version="v1",
            messages=[{"role": "user", "content": _QUESTION}],
        )

        result = await graph.ainvoke(initial)

        assert result.get("error") is None
        assert result["result_set"] == _CARRIER_RESULT
        assert len(result["sql_candidates"]) == 2
        llm.assert_call_count(2)

    @pytest.mark.integration
    async def test_unrecoverable_query_abstains_with_no_result(
        self, provider, warehouse_with_unmodeled_table, verified_store
    ):
        graph, llm = _build_graph(
            provider,
            warehouse_with_unmodeled_table,
            [SqlCandidate(sql="DROP TABLE ecommerce_shipping_carriers", tables_used=[])] * 3,
            verified_store,
        )
        initial = OmniState(
            thread_id="t1",
            dataset_id="ecommerce",
            schema_version="v1",
            messages=[{"role": "user", "content": _QUESTION}],
        )

        result = await graph.ainvoke(initial)

        assert result.get("error") is not None
        assert result.get("result_set") is None
        assert result.get("narration") is None

    @pytest.mark.integration
    async def test_approved_query_hits_fast_path_with_zero_model_calls(
        self, provider, warehouse_with_unmodeled_table, verified_store
    ):
        scope = Scope(tenant="local", dataset="ecommerce", schema_version="v1")
        verified_store.add(
            scope,
            VerifiedQuery(
                question=_QUESTION,
                artifact=_CARRIER_SQL,
                result_signature="sig-1",
                status="approved",
                approved_by="hooman",
                created_at=datetime.now(UTC),
            ),
        )
        graph, llm = _build_graph(provider, warehouse_with_unmodeled_table, [], verified_store)
        initial = OmniState(
            thread_id="t1",
            dataset_id="ecommerce",
            schema_version="v1",
            messages=[{"role": "user", "content": _QUESTION}],
        )

        result = await graph.ainvoke(initial)

        assert result.get("error") is None
        assert result["result_set"] == _CARRIER_RESULT
        assert result["evidence"]["verified_query_hit"] is True
        llm.assert_call_count(0)

    @pytest.mark.integration
    async def test_schema_version_bump_invalidates_the_fast_path(
        self, provider, warehouse_with_unmodeled_table, verified_store
    ):
        """A verified query stored under one schema_version is invisible once
        the running state carries a different one -- no explicit invalidate()
        call needed, since retrieval is namespace-scoped by construction."""
        old_scope = Scope(tenant="local", dataset="ecommerce", schema_version="v1-old")
        verified_store.add(
            old_scope,
            VerifiedQuery(
                question=_QUESTION,
                artifact=_CARRIER_SQL,
                result_signature="sig-1",
                status="approved",
                approved_by="hooman",
                created_at=datetime.now(UTC),
            ),
        )
        graph, llm = _build_graph(
            provider,
            warehouse_with_unmodeled_table,
            [SqlCandidate(sql=_CARRIER_SQL, tables_used=["ecommerce_shipping_carriers"])],
            verified_store,
        )
        initial = OmniState(
            thread_id="t1",
            dataset_id="ecommerce",
            schema_version="v2-new",
            messages=[{"role": "user", "content": _QUESTION}],
        )

        result = await graph.ainvoke(initial)

        assert (
            result["route"] == "fast_path"
        )  # master's first hop; old-version entry is invisible here
        assert result["result_set"] == _CARRIER_RESULT
        llm.assert_call_count(1)


class TestGuardedFallbackDoesNotAffectGovernedPath:
    @pytest.mark.integration
    async def test_governed_question_never_reaches_sql_agent_even_with_fallback_configured(
        self, provider, warehouse_with_unmodeled_table, verified_store
    ):
        graph, llm = _build_graph(
            provider,
            warehouse_with_unmodeled_table,
            [SemanticExtraction(time_phrase=None, filters=[])],
            verified_store,
        )
        initial = OmniState(
            thread_id="t1",
            dataset_id="ecommerce",
            schema_version="v1",
            messages=[{"role": "user", "content": "order count"}],
        )

        result = await graph.ainvoke(initial)

        assert result["route"] == "semantic_agent"
        assert result["matched_metric"] == "order_count"
        assert result["result_set"] == [{"order_count": 3}]
