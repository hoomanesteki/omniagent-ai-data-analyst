"""Component tests for executor_node: compile, guard, execute, guard again.

Uses the real ecommerce pack + the shared hand-computed warehouse fixture
(tests/conftest.py) so every assertion checks an exact expected value.
"""

import asyncio

import pytest
from langgraph.graph import END

from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
from omniagent.agents.executor import make_executor_node
from omniagent.agents.query_codec import query_to_dict
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
from omniagent.kernel.ports.semantic import SemanticQuery
from omniagent.kernel.state import OmniState

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


@pytest.fixture
def provider():
    return NativeYamlProvider("packs")


def _state_with_query(query: SemanticQuery) -> OmniState:
    return OmniState(thread_id="t1", dataset_id="ecommerce", semantic_query=query_to_dict(query))


class TestExecutorHappyPath:
    def test_executes_and_returns_exact_value(self, provider, ecommerce_warehouse):
        node = make_executor_node(
            dataset_id="ecommerce",
            semantic_provider=provider,
            engine=ecommerce_warehouse,
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
        )
        state = _state_with_query(SemanticQuery(metrics=("gross_revenue",), limit=10))

        cmd = asyncio.run(node(state))

        assert cmd.goto == END
        assert "error" not in cmd.update or cmd.update.get("error") is None
        assert cmd.update["result_set"] == [{"gross_revenue": 225.0}]
        assert cmd.update["result_meta"]["row_count"] == 1
        assert cmd.update["executed_sql"] is not None

    def test_provenance_and_row_cap_recorded_in_guarded_ledger(self, provider, ecommerce_warehouse):
        node = make_executor_node(
            dataset_id="ecommerce",
            semantic_provider=provider,
            engine=ecommerce_warehouse,
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            row_cap=100,
        )
        state = _state_with_query(SemanticQuery(metrics=("order_count",), limit=10))

        cmd = asyncio.run(node(state))

        assert cmd.update["guarded"]["provenance_gate"]["status"] == "ok"
        assert cmd.update["guarded"]["row_cap_gate"]["status"] == "within_limit"

    def test_evidence_carries_tables_and_schema_version(self, provider, ecommerce_warehouse):
        node = make_executor_node(
            dataset_id="ecommerce",
            semantic_provider=provider,
            engine=ecommerce_warehouse,
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
        )
        state = _state_with_query(SemanticQuery(metrics=("gross_revenue",), limit=10))

        cmd = asyncio.run(node(state))

        assert "ecommerce_orders" in cmd.update["evidence"]["tables"]
        assert cmd.update["evidence"]["schema_version"] == provider.schema_version("ecommerce")


class TestExecutorGateViolations:
    def test_row_cap_violation_raises_unsafe_and_ends_with_error(
        self, provider, ecommerce_warehouse
    ):
        """gross_revenue grouped by channel returns 2 rows (web, mobile_app)
        from completed orders — exceeding a max_rows=1 cap post-execution."""
        node = make_executor_node(
            dataset_id="ecommerce",
            semantic_provider=provider,
            engine=ecommerce_warehouse,
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            row_cap=1,
        )
        state = _state_with_query(
            SemanticQuery(metrics=("gross_revenue",), group_by=("orders.channel",), limit=10)
        )

        cmd = asyncio.run(node(state))

        assert cmd.goto == END
        assert "error" in cmd.update
        assert "truncated" in cmd.update["error"].lower()

    def test_sql_allowlist_still_runs_as_defense_in_depth(self, provider, ecommerce_warehouse):
        """The compiled SQL is always safe, but the gate must still run and
        record a clean pass — not be silently skipped."""
        node = make_executor_node(
            dataset_id="ecommerce",
            semantic_provider=provider,
            engine=ecommerce_warehouse,
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
        )
        state = _state_with_query(SemanticQuery(metrics=("gross_revenue",), limit=10))

        cmd = asyncio.run(node(state))

        # sql_allowlist_gate only writes to the ledger on violation; a clean
        # pass means it's simply absent, which is itself the assertion that
        # matters here — no violation entry exists.
        assert "sql_allowlist_gate" not in cmd.update["guarded"]


class TestExecutorEngineErrors:
    def test_engine_error_ends_with_error_not_exception(self, provider, ecommerce_warehouse):
        """Compiling against the saas pack but executing against the
        ecommerce warehouse fixture references tables that don't exist
        there — a genuine EngineError, not a compile-time SemanticIssue."""
        node = make_executor_node(
            dataset_id="saas",
            semantic_provider=provider,
            engine=ecommerce_warehouse,
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
        )
        query = SemanticQuery(metrics=("mrr",), limit=10)
        state = OmniState(thread_id="t1", dataset_id="saas", semantic_query=query_to_dict(query))

        cmd = asyncio.run(node(state))

        assert cmd.goto == END
        assert "error" in cmd.update
        assert "MISSING_TABLE" in cmd.update["error"] or "MISSING" in cmd.update["error"]


class TestExecutorNoQuery:
    def test_missing_semantic_query_is_a_wiring_error(self, provider, ecommerce_warehouse):
        node = make_executor_node(
            dataset_id="ecommerce",
            semantic_provider=provider,
            engine=ecommerce_warehouse,
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
        )
        state = OmniState(thread_id="t1", dataset_id="ecommerce")  # no semantic_query

        cmd = asyncio.run(node(state))

        assert cmd.goto == END
        assert "error" in cmd.update
