"""Component tests for sql_agent_node: schema linking, guarded generation, self-correction.

Uses the shared hand-computed `ecommerce_warehouse` fixture (tests/conftest.py)
and a `ScriptedLLM` so every attempt sequence is deterministic and every
assertion checks an exact expected value, matching test_executor_node.py's
conventions for the governed path.
"""

import asyncio

from langgraph.graph import END

from omniagent.agents.sql_agent import make_sql_agent_node
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

_COMPLETED_ORDER_COUNT_SQL = (
    "SELECT COUNT(*) AS n FROM ecommerce_orders WHERE order_status = 'completed'"
)


def _state(question: str = "how many orders are completed") -> OmniState:
    return OmniState(
        thread_id="t1",
        dataset_id="ecommerce",
        messages=[{"role": "user", "content": question}],
    )


class TestSqlAgentHappyPath:
    def test_first_candidate_executes_and_returns_exact_value(self, ecommerce_warehouse):
        llm = ScriptedLLM(
            [SqlCandidate(sql=_COMPLETED_ORDER_COUNT_SQL, tables_used=["ecommerce_orders"])]
        )
        node = make_sql_agent_node(
            dataset_id="ecommerce",
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="m",
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
        )

        cmd = asyncio.run(node(_state()))

        assert cmd.goto == "narrator"
        assert cmd.update["result_set"] == [{"n": 3}]
        assert cmd.update["executed_sql"] == _COMPLETED_ORDER_COUNT_SQL
        assert len(cmd.update["sql_candidates"]) == 1
        llm.assert_call_count(1)

    def test_schema_linking_passes_real_table_columns_to_the_model(self, ecommerce_warehouse):
        llm = ScriptedLLM(
            [SqlCandidate(sql=_COMPLETED_ORDER_COUNT_SQL, tables_used=["ecommerce_orders"])]
        )
        node = make_sql_agent_node(
            dataset_id="ecommerce",
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="m",
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
        )

        asyncio.run(node(_state()))

        schema = llm.calls[0]["req"]["schema"]
        assert "ecommerce_orders" in schema["tables"]
        columns = {c["name"] for c in schema["tables"]["ecommerce_orders"]}
        assert {"order_id", "order_status", "order_total"} <= columns

    def test_llm_calls_and_model_calls_by_node_are_tracked(self, ecommerce_warehouse):
        llm = ScriptedLLM(
            [SqlCandidate(sql=_COMPLETED_ORDER_COUNT_SQL, tables_used=["ecommerce_orders"])]
        )
        node = make_sql_agent_node(
            dataset_id="ecommerce",
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="m",
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
        )

        cmd = asyncio.run(node(_state()))

        assert cmd.update["llm_calls"] == 1
        assert cmd.update["model_calls_by_node"]["sql_agent"] == 1


class TestSqlAgentSelfCorrection:
    def test_unsafe_first_candidate_retries_and_succeeds(self, ecommerce_warehouse):
        llm = ScriptedLLM(
            [
                SqlCandidate(sql="DROP TABLE ecommerce_orders", tables_used=[]),
                SqlCandidate(sql=_COMPLETED_ORDER_COUNT_SQL, tables_used=["ecommerce_orders"]),
            ]
        )
        node = make_sql_agent_node(
            dataset_id="ecommerce",
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="m",
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            max_retries=2,
        )

        cmd = asyncio.run(node(_state()))

        assert cmd.goto == "narrator"
        assert cmd.update["result_set"] == [{"n": 3}]
        assert len(cmd.update["sql_candidates"]) == 2
        llm.assert_call_count(2)

    def test_retry_prompt_carries_prior_error_and_sql(self, ecommerce_warehouse):
        llm = ScriptedLLM(
            [
                SqlCandidate(sql="DROP TABLE ecommerce_orders", tables_used=[]),
                SqlCandidate(sql=_COMPLETED_ORDER_COUNT_SQL, tables_used=["ecommerce_orders"]),
            ]
        )
        node = make_sql_agent_node(
            dataset_id="ecommerce",
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="m",
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            max_retries=2,
        )

        asyncio.run(node(_state()))

        second_req = llm.calls[1]["req"]
        assert second_req["prior_attempt_sql"] == "DROP TABLE ecommerce_orders"
        assert "DROP" in second_req["prior_error"]

    def test_post_execution_gate_violation_also_retries(self, ecommerce_warehouse):
        """A candidate that executes fine but returns too many rows fails the
        post-execution row_cap_gate, not the pre-execution allowlist -- a
        distinct retry trigger from an unsafe-SQL or engine-error rejection."""
        llm = ScriptedLLM(
            [
                SqlCandidate(
                    sql="SELECT order_id, order_total FROM ecommerce_orders",
                    tables_used=["ecommerce_orders"],
                ),
                SqlCandidate(sql=_COMPLETED_ORDER_COUNT_SQL, tables_used=["ecommerce_orders"]),
            ]
        )
        node = make_sql_agent_node(
            dataset_id="ecommerce",
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="m",
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            max_retries=2,
            row_cap=1,
        )

        cmd = asyncio.run(node(_state()))

        assert cmd.goto == "narrator"
        assert cmd.update["result_set"] == [{"n": 3}]
        assert len(cmd.update["sql_candidates"]) == 2
        second_req = llm.calls[1]["req"]
        assert "prior_error" in second_req

    def test_broken_sql_that_fails_at_the_engine_also_retries(self, ecommerce_warehouse):
        llm = ScriptedLLM(
            [
                SqlCandidate(sql="SELECT * FROM nonexistent_table", tables_used=[]),
                SqlCandidate(sql=_COMPLETED_ORDER_COUNT_SQL, tables_used=["ecommerce_orders"]),
            ]
        )
        node = make_sql_agent_node(
            dataset_id="ecommerce",
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="m",
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            max_retries=2,
        )

        cmd = asyncio.run(node(_state()))

        assert cmd.goto == "narrator"
        assert cmd.update["result_set"] == [{"n": 3}]
        second_req = llm.calls[1]["req"]
        assert (
            "MISSING_TABLE" in second_req["prior_error"]
            or "nonexistent_table" in second_req["prior_error"]
        )


class TestSqlAgentAbstain:
    def test_exhausts_retry_budget_and_abstains_with_no_result(self, ecommerce_warehouse):
        llm = ScriptedLLM([SqlCandidate(sql="DROP TABLE ecommerce_orders", tables_used=[])] * 3)
        node = make_sql_agent_node(
            dataset_id="ecommerce",
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="m",
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            max_retries=2,
        )

        cmd = asyncio.run(node(_state()))

        assert cmd.goto == END
        assert cmd.update["error"] is not None
        assert "result_set" not in cmd.update
        assert len(cmd.update["sql_candidates"]) == 3
        llm.assert_call_count(3)

    def test_max_retries_zero_means_exactly_one_attempt(self, ecommerce_warehouse):
        llm = ScriptedLLM([SqlCandidate(sql="DROP TABLE ecommerce_orders", tables_used=[])])
        node = make_sql_agent_node(
            dataset_id="ecommerce",
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="m",
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            max_retries=0,
        )

        cmd = asyncio.run(node(_state()))

        assert cmd.goto == END
        llm.assert_call_count(1)
