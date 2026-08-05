"""Component tests for fast_path_node: cache-first execution of verified queries.

Uses the shared hand-computed `ecommerce_warehouse` fixture and a real
`DuckDBVerifiedQueryStore` (real DuckDB VSS + real FastEmbedProvider) rather
than a fake, since genuine embedding-similarity retrieval is exactly the
behavior under test.
"""

import asyncio
from datetime import UTC, datetime

import pytest

from omniagent.adapters.embeddings import FastEmbedProvider
from omniagent.adapters.vectors import DuckDBVSSStore
from omniagent.agents.fast_path import make_fast_path_node
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
from omniagent.kernel.ports.identity import Scope
from omniagent.kernel.ports.stores import VerifiedQuery
from omniagent.kernel.state import OmniState
from omniagent.memory.verified_queries import DuckDBVerifiedQueryStore

# See tests/contract/test_verified_queries.py's pytestmark comment: shared
# xdist_group so concurrent workers don't race to load the real embedding
# model at once.
pytestmark = pytest.mark.xdist_group(name="fastembed")

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

_ORDER_COUNT_SQL = "SELECT COUNT(*) AS n FROM ecommerce_orders WHERE order_status = 'completed'"


@pytest.fixture(scope="module")
def embedder():
    return FastEmbedProvider()


@pytest.fixture
def store(embedder):
    with DuckDBVSSStore(dim=embedder.dim) as vstore:
        yield DuckDBVerifiedQueryStore(vstore, embedder, min_score=0.9)


@pytest.fixture
def scope():
    return Scope(tenant="local", dataset="ecommerce", schema_version="v1")


def _state(question: str = "how many orders are completed") -> OmniState:
    return OmniState(
        thread_id="t1",
        dataset_id="ecommerce",
        schema_version="v1",
        messages=[{"role": "user", "content": question}],
    )


def _node(store, engine):
    return make_fast_path_node(
        dataset_id="ecommerce",
        engine=engine,
        verified_query_store=store,
        guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
        fallback_route="sql_agent",
    )


class TestFastPathHit:
    def test_verified_query_executes_and_returns_exact_value(
        self, store, scope, ecommerce_warehouse
    ):
        store.add(
            scope,
            VerifiedQuery(
                question="how many orders are completed",
                artifact=_ORDER_COUNT_SQL,
                result_signature="sig-1",
                status="approved",
                approved_by="hooman",
                created_at=datetime.now(UTC),
            ),
        )
        node = _node(store, ecommerce_warehouse)

        cmd = asyncio.run(node(_state()))

        assert cmd.goto == "narrator"
        assert cmd.update["result_set"] == [{"n": 3}]
        assert cmd.update["evidence"]["verified_query_hit"] is True

    def test_paraphrase_of_verified_question_still_hits(self, store, scope, ecommerce_warehouse):
        store.add(
            scope,
            VerifiedQuery(
                question="how many orders are completed",
                artifact=_ORDER_COUNT_SQL,
                result_signature="sig-1",
                status="approved",
                approved_by="hooman",
                created_at=datetime.now(UTC),
            ),
        )
        node = _node(store, ecommerce_warehouse)

        cmd = asyncio.run(node(_state("how many orders have been completed")))

        assert cmd.goto == "narrator"
        assert cmd.update["result_set"] == [{"n": 3}]


class TestFastPathMiss:
    def test_empty_store_falls_through_to_fallback_route(self, store, ecommerce_warehouse):
        node = _node(store, ecommerce_warehouse)

        cmd = asyncio.run(node(_state()))

        assert cmd.goto == "sql_agent"
        assert cmd.update == {}

    def test_unrelated_question_falls_through_despite_a_verified_entry_existing(
        self, store, scope, ecommerce_warehouse
    ):
        store.add(
            scope,
            VerifiedQuery(
                question="how many orders are completed",
                artifact=_ORDER_COUNT_SQL,
                result_signature="sig-1",
                status="approved",
                approved_by="hooman",
                created_at=datetime.now(UTC),
            ),
        )
        node = _node(store, ecommerce_warehouse)

        cmd = asyncio.run(node(_state("what is the weather in paris today")))

        assert cmd.goto == "sql_agent"

    def test_proposed_status_is_not_treated_as_verified(self, store, scope, ecommerce_warehouse):
        store.add(
            scope,
            VerifiedQuery(
                question="how many orders are completed",
                artifact=_ORDER_COUNT_SQL,
                result_signature="sig-1",
                status="proposed",
                approved_by="",
                created_at=datetime.now(UTC),
            ),
        )
        node = _node(store, ecommerce_warehouse)

        cmd = asyncio.run(node(_state()))

        assert cmd.goto == "sql_agent"

    def test_non_string_artifact_falls_through(self, store, scope, ecommerce_warehouse):
        store.add(
            scope,
            VerifiedQuery(
                question="how many orders are completed",
                artifact={"metric": "order_count"},
                result_signature="sig-1",
                status="approved",
                approved_by="hooman",
                created_at=datetime.now(UTC),
            ),
        )
        node = _node(store, ecommerce_warehouse)

        cmd = asyncio.run(node(_state()))

        assert cmd.goto == "sql_agent"

    def test_stale_query_that_now_violates_a_gate_falls_through(
        self, store, scope, ecommerce_warehouse
    ):
        store.add(
            scope,
            VerifiedQuery(
                question="how many orders are completed",
                artifact="DROP TABLE ecommerce_orders",
                result_signature="sig-1",
                status="approved",
                approved_by="hooman",
                created_at=datetime.now(UTC),
            ),
        )
        node = _node(store, ecommerce_warehouse)

        cmd = asyncio.run(node(_state()))

        assert cmd.goto == "sql_agent"

    def test_stale_query_that_now_errors_at_the_engine_falls_through(
        self, store, scope, ecommerce_warehouse
    ):
        store.add(
            scope,
            VerifiedQuery(
                question="how many orders are completed",
                artifact="SELECT * FROM a_table_that_no_longer_exists",
                result_signature="sig-1",
                status="approved",
                approved_by="hooman",
                created_at=datetime.now(UTC),
            ),
        )
        node = _node(store, ecommerce_warehouse)

        cmd = asyncio.run(node(_state()))

        assert cmd.goto == "sql_agent"

    def test_query_that_now_violates_a_post_execution_gate_falls_through(
        self, store, scope, ecommerce_warehouse
    ):
        """Executes fine but returns more rows than the configured cap allows --
        a distinct rejection path from a pre-execution allowlist violation."""
        store.add(
            scope,
            VerifiedQuery(
                question="how many orders are completed",
                artifact="SELECT order_id, order_total FROM ecommerce_orders",
                result_signature="sig-1",
                status="approved",
                approved_by="hooman",
                created_at=datetime.now(UTC),
            ),
        )
        node = make_fast_path_node(
            dataset_id="ecommerce",
            engine=ecommerce_warehouse,
            verified_query_store=store,
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            fallback_route="sql_agent",
            row_cap=1,
        )

        cmd = asyncio.run(node(_state()))

        assert cmd.goto == "sql_agent"

    def test_different_schema_version_is_not_visible(self, store, ecommerce_warehouse):
        other_scope = Scope(tenant="local", dataset="ecommerce", schema_version="v2-different")
        store.add(
            other_scope,
            VerifiedQuery(
                question="how many orders are completed",
                artifact=_ORDER_COUNT_SQL,
                result_signature="sig-1",
                status="approved",
                approved_by="hooman",
                created_at=datetime.now(UTC),
            ),
        )
        node = _node(store, ecommerce_warehouse)

        cmd = asyncio.run(node(_state()))  # state.schema_version == "v1"

        assert cmd.goto == "sql_agent"
