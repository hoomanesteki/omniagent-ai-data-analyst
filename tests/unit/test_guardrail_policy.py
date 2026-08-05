"""Unit tests for GuardrailPolicy: gate composition and orchestration."""

import asyncio
from typing import Any

import pytest

from omniagent.kernel.gates import GuardrailPolicy, Unsafe
from omniagent.kernel.state import OmniState


async def _passing_gate(state: OmniState, *, config: dict[str, Any]) -> OmniState:
    if state.guarded is None:
        state.guarded = {}
    return state


async def _failing_gate(state: OmniState, *, config: dict[str, Any]) -> OmniState:
    raise Unsafe(reason="failing_gate violation")


async def _other_failing_gate(state: OmniState, *, config: dict[str, Any]) -> OmniState:
    raise Unsafe(reason="other_failing_gate violation")


async def _buggy_gate(state: OmniState, *, config: dict[str, Any]) -> OmniState:
    raise ValueError("unexpected bug")


class TestGuardrailPolicyHappyPath:
    """All gates pass: state flows through, no exception."""

    def test_single_passing_gate(self) -> None:
        policy = GuardrailPolicy(gates=[_passing_gate])
        state = OmniState(thread_id="t1")

        result = asyncio.run(policy.apply(state))

        assert result is state
        assert result.guarded == {}

    def test_multiple_passing_gates_all_run(self) -> None:
        calls = []

        async def gate_a(state: OmniState, *, config: dict[str, Any]) -> OmniState:
            calls.append("a")
            return state

        async def gate_b(state: OmniState, *, config: dict[str, Any]) -> OmniState:
            calls.append("b")
            return state

        policy = GuardrailPolicy(gates=[gate_a, gate_b])
        state = OmniState(thread_id="t1")

        asyncio.run(policy.apply(state))

        assert calls == ["a", "b"]

    def test_empty_gate_list_returns_state_unchanged(self) -> None:
        policy = GuardrailPolicy(gates=[])
        state = OmniState(thread_id="t1")

        result = asyncio.run(policy.apply(state))

        assert result is state

    def test_initializes_guarded_dict_if_none(self) -> None:
        policy = GuardrailPolicy(gates=[])
        state = OmniState(thread_id="t1")
        assert state.guarded is None

        result = asyncio.run(policy.apply(state))

        assert result.guarded is not None
        assert isinstance(result.guarded, dict)

    def test_gate_results_are_actually_awaited(self) -> None:
        """A gate's async body must run to completion, not be left as a
        dangling coroutine — this is what apply() previously got wrong."""

        mutated = {"ran": False}

        async def mutating_gate(state: OmniState, *, config: dict[str, Any]) -> OmniState:
            mutated["ran"] = True
            if state.guarded is None:
                state.guarded = {}
            state.guarded["mutating_gate"] = {"status": "ok"}
            return state

        policy = GuardrailPolicy(gates=[mutating_gate])
        state = OmniState(thread_id="t1")

        result = asyncio.run(policy.apply(state))

        assert mutated["ran"] is True
        assert result.guarded["mutating_gate"] == {"status": "ok"}


class TestGuardrailPolicyViolations:
    """A gate raising Unsafe ultimately blocks, without short-circuiting."""

    def test_single_violation_raises_unsafe(self) -> None:
        policy = GuardrailPolicy(gates=[_failing_gate])
        state = OmniState(thread_id="t1")

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(policy.apply(state))

        assert "failing_gate violation" in exc_info.value.reason

    def test_violation_recorded_in_guarded_ledger(self) -> None:
        policy = GuardrailPolicy(gates=[_failing_gate])
        state = OmniState(thread_id="t1")

        with pytest.raises(Unsafe):
            asyncio.run(policy.apply(state))

        assert state.guarded["_failing_gate"]["unsafe"] is True
        assert state.guarded["_failing_gate"]["reason"] == "failing_gate violation"

    def test_no_short_circuit_all_gates_run_despite_earlier_violation(self) -> None:
        calls = []

        async def tracked_gate_a(state: OmniState, *, config: dict[str, Any]) -> OmniState:
            calls.append("a")
            raise Unsafe(reason="a violation")

        async def tracked_gate_b(state: OmniState, *, config: dict[str, Any]) -> OmniState:
            calls.append("b")
            return state

        async def tracked_gate_c(state: OmniState, *, config: dict[str, Any]) -> OmniState:
            calls.append("c")
            raise Unsafe(reason="c violation")

        policy = GuardrailPolicy(gates=[tracked_gate_a, tracked_gate_b, tracked_gate_c])
        state = OmniState(thread_id="t1")

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(policy.apply(state))

        # Every gate ran, including b and c after a's violation.
        assert calls == ["a", "b", "c"]
        # Both violations are represented in the final raised reason.
        assert "a violation" in exc_info.value.reason
        assert "c violation" in exc_info.value.reason

    def test_multiple_violations_all_recorded_in_ledger(self) -> None:
        policy = GuardrailPolicy(gates=[_failing_gate, _other_failing_gate])
        state = OmniState(thread_id="t1")

        with pytest.raises(Unsafe):
            asyncio.run(policy.apply(state))

        assert state.guarded["_failing_gate"]["unsafe"] is True
        assert state.guarded["_other_failing_gate"]["unsafe"] is True

    def test_passing_gate_after_violation_still_updates_state(self) -> None:
        async def gate_a(state: OmniState, *, config: dict[str, Any]) -> OmniState:
            raise Unsafe(reason="a violation")

        async def gate_b(state: OmniState, *, config: dict[str, Any]) -> OmniState:
            if state.guarded is None:
                state.guarded = {}
            state.guarded["gate_b"] = {"status": "ok"}
            return state

        policy = GuardrailPolicy(gates=[gate_a, gate_b])
        state = OmniState(thread_id="t1")

        with pytest.raises(Unsafe):
            asyncio.run(policy.apply(state))

        assert state.guarded["gate_b"] == {"status": "ok"}


class TestGuardrailPolicyUnexpectedErrors:
    """A gate raising a non-Unsafe exception fails closed, exactly like a
    real Unsafe would -- a safety gate that crashes is not a gate that
    passed. The crash is still recorded in `guarded` for the audit trail,
    and the remaining gates still run (for full audit coverage), but
    `apply()` raises once the loop ends either way."""

    def test_unexpected_exception_raises_unsafe(self) -> None:
        policy = GuardrailPolicy(gates=[_buggy_gate])
        state = OmniState(thread_id="t1")

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(policy.apply(state))

        assert "_buggy_gate" in exc_info.value.reason
        assert state.guarded["_buggy_gate"]["exception_type"] == "ValueError"
        assert "unexpected bug" in state.guarded["_buggy_gate"]["error"]
        assert state.guarded["_buggy_gate"]["unsafe"] is True

    def test_unexpected_exception_does_not_block_remaining_gates(self) -> None:
        calls = []

        async def gate_a(state: OmniState, *, config: dict[str, Any]) -> OmniState:
            calls.append("a")
            raise ValueError("boom")

        async def gate_b(state: OmniState, *, config: dict[str, Any]) -> OmniState:
            calls.append("b")
            return state

        policy = GuardrailPolicy(gates=[gate_a, gate_b])
        state = OmniState(thread_id="t1")

        with pytest.raises(Unsafe):
            asyncio.run(policy.apply(state))

        assert calls == ["a", "b"]
        assert state.guarded["gate_a"]["exception_type"] == "ValueError"

    def test_mix_of_unsafe_and_unexpected_errors(self) -> None:
        async def gate_unsafe(state: OmniState, *, config: dict[str, Any]) -> OmniState:
            raise Unsafe(reason="blocked")

        async def gate_buggy(state: OmniState, *, config: dict[str, Any]) -> OmniState:
            raise RuntimeError("crashed")

        policy = GuardrailPolicy(gates=[gate_unsafe, gate_buggy])
        state = OmniState(thread_id="t1")

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(policy.apply(state))

        assert "blocked" in exc_info.value.reason
        assert state.guarded["gate_buggy"]["exception_type"] == "RuntimeError"
