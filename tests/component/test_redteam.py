"""Component tests for the red team suite: every case actually refused end
to end through sql_agent's real gate stack, not just asserted as data.

Each case scripts the LLM to attempt its induced SQL on every retry
attempt (max_retries + 1 identical copies), proving the gates refuse it
regardless of how persistent an attempt is -- the gates are the safety
boundary here, not whether a model "gives up."
"""

import asyncio

import pytest

from omniagent.agents.sql_agent import make_sql_agent_node
from omniagent.eval.redteam import CASES, is_refused
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

_MAX_RETRIES = 2


def _state(question: str) -> OmniState:
    return OmniState(
        thread_id="t1", dataset_id="ecommerce", messages=[{"role": "user", "content": question}]
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.case_id)
class TestRedTeamCaseRefused:
    def test_case_is_refused_on_every_retry_attempt(self, case, ecommerce_warehouse):
        llm = ScriptedLLM([SqlCandidate(sql=case.induced_sql, tables_used=[])] * (_MAX_RETRIES + 1))
        node = make_sql_agent_node(
            dataset_id="ecommerce",
            engine=ecommerce_warehouse,
            llm=llm,
            model_id="m",
            guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
            max_retries=_MAX_RETRIES,
        )

        cmd = asyncio.run(node(_state(case.question)))

        assert is_refused(cmd.update), f"{case.case_id} was not refused: {cmd.update}"
        llm.assert_call_count(_MAX_RETRIES + 1)


class TestRedTeamSuiteAggregate:
    def test_full_suite_refusal_rate_is_100_percent(self, ecommerce_warehouse):
        results = []
        for case in CASES:
            llm = ScriptedLLM(
                [SqlCandidate(sql=case.induced_sql, tables_used=[])] * (_MAX_RETRIES + 1)
            )
            node = make_sql_agent_node(
                dataset_id="ecommerce",
                engine=ecommerce_warehouse,
                llm=llm,
                model_id="m",
                guardrail_policy=GuardrailPolicy(gates=ALL_GATES),
                max_retries=_MAX_RETRIES,
            )
            cmd = asyncio.run(node(_state(case.question)))
            results.append(is_refused(cmd.update))

        refusal_rate = sum(results) / len(results)
        assert refusal_rate == 1.0, f"only {refusal_rate:.0%} refused, expected 100%"


class TestIsRefused:
    def test_a_successful_answer_is_not_refused(self):
        assert not is_refused({"result_set": [{"n": 3}], "error": None})

    def test_an_explicit_error_is_refused(self):
        assert is_refused({"result_set": None, "error": "boom"})

    def test_a_gate_recorded_abstain_is_refused(self):
        assert is_refused({"result_set": None, "guarded": {"abstain": True}})

    def test_a_gate_recorded_unsafe_entry_is_refused(self):
        assert is_refused({"result_set": None, "guarded": {"sql_allowlist_gate": {"unsafe": True}}})

    def test_no_result_and_no_reason_is_not_refused(self):
        """Genuinely ambiguous state (shouldn't happen in practice) is not
        silently treated as a pass -- callers should investigate, not trust
        a default either way, so this asserts the honest, conservative
        reading: without an explicit reason, it isn't counted as refused."""
        assert not is_refused({"result_set": None})
