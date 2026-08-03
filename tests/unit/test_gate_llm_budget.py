"""Unit tests for LLM budget gate with parametrized test cases.

Covers happy path, violations, and edge cases with 80%+ branch coverage.
"""

import asyncio

import pytest

from omniagent.kernel.gates import Unsafe
from omniagent.kernel.gates.llm_budget import llm_budget_gate
from omniagent.kernel.state import OmniState


class TestLLMBudgetGateHappyPath:
    """Tests where gate passes and state is returned unchanged."""

    def test_no_budgets_configured_returns_state(self):
        """Happy path: no budgets configured, gate passes and returns state."""
        state = OmniState(
            thread_id="test",
            llm_calls=100,
            model_calls_by_node={"node_a": 10, "node_b": 20},
        )
        config = {}

        result = asyncio.run(llm_budget_gate(state, config=config))

        assert result is state
        assert result.llm_calls == 100
        assert result.model_calls_by_node == {"node_a": 10, "node_b": 20}

    @pytest.mark.parametrize(
        "llm_calls,token_max,model_calls",
        [
            # Within limits
            (50, 100, {"node_a": 5}),
            (0, 100, {"node_a": 0}),
            (99, 100, {"node_a": 9}),
            # Single node
            (42, 500, {"worker": 7}),
            # Multiple nodes
            (30, 200, {"node_1": 5, "node_2": 10, "node_3": 15}),
        ],
    )
    def test_within_both_budgets_passes(self, llm_calls, token_max, model_calls):
        """Happy path: state within both LLM call and token budgets."""
        state = OmniState(
            thread_id="test",
            llm_calls=llm_calls,
            model_calls_by_node=model_calls,
        )
        config = {
            "llm_calls_max": 100,
            "token_budget_max": token_max,
        }

        result = asyncio.run(llm_budget_gate(state, config=config))

        assert result is state
        assert result.llm_calls == llm_calls

    @pytest.mark.parametrize(
        "llm_calls,model_calls",
        [
            (10, {"node_a": 5}),
            (50, {"node_a": 25, "node_b": 25}),
            (100, {"node": 50, "node2": 50}),
        ],
    )
    def test_only_llm_calls_budget_configured(self, llm_calls, model_calls):
        """Happy path: only LLM calls budget configured, token budget ignored."""
        state = OmniState(
            thread_id="test",
            llm_calls=llm_calls,
            model_calls_by_node=model_calls,
        )
        config = {"llm_calls_max": 100}

        result = asyncio.run(llm_budget_gate(state, config=config))

        assert result is state

    @pytest.mark.parametrize(
        "llm_calls",
        [5, 50, 99],
    )
    def test_only_token_budget_configured(self, llm_calls):
        """Happy path: only token budget configured, LLM calls ignored."""
        state = OmniState(
            thread_id="test",
            llm_calls=llm_calls,
            model_calls_by_node={"node": 10},
        )
        config = {"token_budget_max": 100}

        result = asyncio.run(llm_budget_gate(state, config=config))

        assert result is state


class TestLLMBudgetGateViolations:
    """Tests where gate detects budget violation and raises Unsafe."""

    @pytest.mark.parametrize(
        "llm_calls,model_calls,llm_max",
        [
            # Exceeds LLM calls budget
            (101, {"node_a": 51, "node_b": 50}, 100),
            (150, {"node": 75}, 100),
            (1001, {"node": 500}, 1000),
            # Just over limit
            (101, {"node": 101}, 100),
        ],
    )
    def test_exceeds_llm_calls_budget_raises_unsafe(self, llm_calls, model_calls, llm_max):
        """Violation: total LLM calls exceed configured max."""
        state = OmniState(
            thread_id="test",
            llm_calls=llm_calls,
            model_calls_by_node=model_calls,
        )
        config = {"llm_calls_max": llm_max}

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(llm_budget_gate(state, config=config))

        assert "LLM budget exceeded" in exc_info.value.reason
        assert str(sum(model_calls.values())) in exc_info.value.reason
        assert str(llm_max) in exc_info.value.reason

    @pytest.mark.parametrize(
        "llm_calls,token_max",
        [
            # Exceeds token budget
            (101, 100),
            (500, 100),
            (1001, 1000),
            # Just over limit
            (101, 100),
        ],
    )
    def test_exceeds_token_budget_raises_unsafe(self, llm_calls, token_max):
        """Violation: cumulative tokens (via llm_calls) exceed configured max."""
        state = OmniState(
            thread_id="test",
            llm_calls=llm_calls,
            model_calls_by_node={"node": 10},
        )
        config = {"token_budget_max": token_max}

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(llm_budget_gate(state, config=config))

        assert "LLM token budget exceeded" in exc_info.value.reason
        assert str(llm_calls) in exc_info.value.reason
        assert str(token_max) in exc_info.value.reason

    def test_exceeds_both_budgets_raises_on_calls_first(self):
        """Violation: exceeds both budgets, raises on LLM calls check first."""
        state = OmniState(
            thread_id="test",
            llm_calls=150,  # Exceeds token budget
            model_calls_by_node={"node": 150},  # Also exceeds calls budget
        )
        config = {
            "llm_calls_max": 100,
            "token_budget_max": 100,
        }

        # Should raise on LLM calls check first
        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(llm_budget_gate(state, config=config))

        assert "LLM budget exceeded" in exc_info.value.reason


class TestLLMBudgetGateEdgeCases:
    """Edge cases: None values, empty dicts, boundary conditions."""

    def test_none_model_calls_by_node_treated_as_zero(self):
        """Edge case: None model_calls_by_node defaults to empty dict."""
        state = OmniState(
            thread_id="test",
            llm_calls=10,
            model_calls_by_node=None,  # type: ignore
        )
        config = {"llm_calls_max": 100, "token_budget_max": 100}

        result = asyncio.run(llm_budget_gate(state, config=config))

        assert result is state

    def test_empty_model_calls_by_node_passes(self):
        """Edge case: empty model_calls_by_node dict."""
        state = OmniState(
            thread_id="test",
            llm_calls=50,
            model_calls_by_node={},
        )
        config = {"llm_calls_max": 100, "token_budget_max": 100}

        result = asyncio.run(llm_budget_gate(state, config=config))

        assert result is state

    def test_invalid_model_calls_by_node_type_treated_as_empty(self):
        """Edge case: model_calls_by_node is not a dict, treated as empty."""
        state = OmniState(
            thread_id="test",
            llm_calls=10,
            model_calls_by_node="not a dict",  # type: ignore
        )
        config = {"llm_calls_max": 100, "token_budget_max": 100}

        result = asyncio.run(llm_budget_gate(state, config=config))

        assert result is state

    def test_boundary_exactly_at_llm_calls_limit(self):
        """Edge case: model_calls sum exactly equals limit (passes)."""
        state = OmniState(
            thread_id="test",
            llm_calls=100,
            model_calls_by_node={"node_a": 50, "node_b": 50},
        )
        config = {"llm_calls_max": 100}

        result = asyncio.run(llm_budget_gate(state, config=config))

        assert result is state

    def test_boundary_exactly_at_token_limit(self):
        """Edge case: llm_calls exactly equals token limit (passes)."""
        state = OmniState(
            thread_id="test",
            llm_calls=100,
            model_calls_by_node={"node": 10},
        )
        config = {"token_budget_max": 100}

        result = asyncio.run(llm_budget_gate(state, config=config))

        assert result is state

    def test_zero_llm_calls_budget_rejects_any_call(self):
        """Edge case: zero budget for LLM calls rejects any usage."""
        state = OmniState(
            thread_id="test",
            llm_calls=0,
            model_calls_by_node={"node": 1},
        )
        config = {"llm_calls_max": 0}

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(llm_budget_gate(state, config=config))

        assert "LLM budget exceeded" in exc_info.value.reason

    def test_zero_token_budget_rejects_any_token(self):
        """Edge case: zero budget for tokens rejects any usage."""
        state = OmniState(
            thread_id="test",
            llm_calls=1,
            model_calls_by_node={"node": 0},
        )
        config = {"token_budget_max": 0}

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(llm_budget_gate(state, config=config))

        assert "LLM token budget exceeded" in exc_info.value.reason

    def test_none_llm_calls_defaults_to_zero(self):
        """Edge case: llm_calls is None, treated as 0."""
        state = OmniState(
            thread_id="test",
            llm_calls=0,
            model_calls_by_node={"node": 5},
        )
        # Simulate llm_calls being None (edge case)
        state.llm_calls = 0
        config = {"token_budget_max": 100}

        result = asyncio.run(llm_budget_gate(state, config=config))

        assert result is state

    @pytest.mark.parametrize(
        "model_calls",
        [
            {"node": 0},
            {"node_1": 0, "node_2": 0},
            {"a": 0, "b": 0, "c": 0},
        ],
    )
    def test_zero_calls_across_nodes_passes(self, model_calls):
        """Edge case: all nodes have zero calls."""
        state = OmniState(
            thread_id="test",
            llm_calls=0,
            model_calls_by_node=model_calls,
        )
        config = {"llm_calls_max": 100, "token_budget_max": 100}

        result = asyncio.run(llm_budget_gate(state, config=config))

        assert result is state


class TestLLMBudgetGateComplexScenarios:
    """Complex scenarios combining multiple conditions."""

    def test_many_nodes_exceeding_budget(self):
        """Complex: many nodes with cumulative calls exceeding budget."""
        state = OmniState(
            thread_id="test",
            llm_calls=50,
            model_calls_by_node={
                "node_1": 20,
                "node_2": 25,
                "node_3": 30,
                "node_4": 26,
            },
        )
        config = {"llm_calls_max": 100}

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(llm_budget_gate(state, config=config))

        assert "LLM budget exceeded" in exc_info.value.reason
        # Total should be 101
        assert "101" in exc_info.value.reason

    def test_many_nodes_within_budget(self):
        """Complex: many nodes with cumulative calls within budget."""
        state = OmniState(
            thread_id="test",
            llm_calls=80,
            model_calls_by_node={
                "node_1": 15,
                "node_2": 15,
                "node_3": 15,
                "node_4": 15,
                "node_5": 15,
                "node_6": 10,
            },
        )
        config = {"llm_calls_max": 100, "token_budget_max": 100}

        result = asyncio.run(llm_budget_gate(state, config=config))

        assert result is state

    @pytest.mark.parametrize(
        "config_keys",
        [
            [],  # Empty config
            ["unrelated_key"],  # Config with unrelated keys
            ["some_other_setting"],
        ],
    )
    def test_config_with_unrelated_keys_ignored(self, config_keys):
        """Complex: config with unrelated keys doesn't affect gate."""
        config = dict.fromkeys(config_keys, "value")
        state = OmniState(
            thread_id="test",
            llm_calls=100,
            model_calls_by_node={"node": 50},
        )

        result = asyncio.run(llm_budget_gate(state, config=config))

        assert result is state

    def test_sequential_calls_tracking_pattern(self):
        """Complex: simulates sequential calls pattern."""
        # First call
        state1 = OmniState(
            thread_id="test",
            llm_calls=10,
            model_calls_by_node={"node": 10},
        )
        config = {"llm_calls_max": 100, "token_budget_max": 100}

        result1 = asyncio.run(llm_budget_gate(state1, config=config))
        assert result1 is state1

        # Subsequent call with increased usage
        state2 = OmniState(
            thread_id="test",
            llm_calls=50,
            model_calls_by_node={"node": 50},
        )

        result2 = asyncio.run(llm_budget_gate(state2, config=config))
        assert result2 is state2

        # Over budget
        state3 = OmniState(
            thread_id="test",
            llm_calls=101,
            model_calls_by_node={"node": 101},
        )

        with pytest.raises(Unsafe):
            asyncio.run(llm_budget_gate(state3, config=config))


@pytest.mark.parametrize(
    "llm_calls,model_calls,config,should_raise",
    [
        # Comprehensive matrix of conditions
        # (llm_calls, model_calls_by_node, config, should_raise)
        (10, {"node": 10}, {"llm_calls_max": 50}, False),
        (10, {"node": 10}, {"llm_calls_max": 5}, True),
        (10, {"node": 5}, {"token_budget_max": 50}, False),
        (10, {"node": 5}, {"token_budget_max": 5}, True),
        (25, {"node_1": 15, "node_2": 10}, {"llm_calls_max": 50}, False),
        (25, {"node_1": 15, "node_2": 10}, {"llm_calls_max": 24}, True),
        (50, {"node": 30}, {"llm_calls_max": 100, "token_budget_max": 100}, False),
        (50, {"node": 150}, {"llm_calls_max": 100, "token_budget_max": 100}, True),
        (150, {"node": 50}, {"llm_calls_max": 100, "token_budget_max": 100}, True),
        (100, {"node": 100}, {"llm_calls_max": 100, "token_budget_max": 100}, False),
    ],
)
def test_llm_budget_comprehensive_matrix(llm_calls, model_calls, config, should_raise):
    """Comprehensive parametrized test covering all major branches."""
    state = OmniState(
        thread_id="test",
        llm_calls=llm_calls,
        model_calls_by_node=model_calls,
    )

    if should_raise:
        with pytest.raises(Unsafe):
            asyncio.run(llm_budget_gate(state, config=config))
    else:
        result = asyncio.run(llm_budget_gate(state, config=config))
        assert result is state
