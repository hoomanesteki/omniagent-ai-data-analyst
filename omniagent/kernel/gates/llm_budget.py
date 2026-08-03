"""LLM budget gate: track and enforce cumulative LLM call and token limits."""

from typing import Any

from ..state import OmniState
from .exceptions import Unsafe


async def llm_budget_gate(state: OmniState, *, config: dict[str, Any]) -> OmniState:
    """
    LLM budget gate: track cumulative LLM calls and tokens.

    Enforces limits on:
    - Total LLM calls (via state.model_calls_by_node)
    - Cumulative token usage

    Raises Unsafe if either limit is exceeded. Otherwise returns state unchanged.

    Args:
        state: The OmniState to guard.
        config: Configuration dict with optional keys:
            - llm_calls_max (int): Maximum total LLM calls across all nodes.
            - token_budget_max (int): Maximum cumulative tokens allowed.

    Returns:
        The state unchanged if within budget.

    Raises:
        Unsafe: If LLM call or token budget is exceeded.
    """
    # Extract budget limits from config with safe defaults
    llm_calls_max: int | None = config.get("llm_calls_max")
    token_budget_max: int | None = config.get("token_budget_max")

    # If no limits are configured, pass through without checks
    if llm_calls_max is None and token_budget_max is None:
        return state

    # Defensive: handle None or missing model_calls_by_node
    model_calls_by_node = state.model_calls_by_node or {}
    if not isinstance(model_calls_by_node, dict):
        model_calls_by_node = {}

    # Calculate total LLM calls across all nodes
    total_llm_calls = sum(model_calls_by_node.values())

    # Check LLM call budget. Compared against the larger of the per-node
    # breakdown and state.llm_calls — a caller may bump llm_calls directly
    # without a matching per-node entry, and that must still be caught.
    effective_calls = max(total_llm_calls, state.llm_calls or 0)
    if llm_calls_max is not None and effective_calls > llm_calls_max:
        raise Unsafe(reason=f"LLM budget exceeded: {total_llm_calls} calls > {llm_calls_max} max")

    # Check token budget
    if token_budget_max is not None:
        # Use state.llm_calls as a proxy for tokens (can be enhanced later
        # with actual token counting from model responses)
        cumulative_tokens = state.llm_calls or 0
        if cumulative_tokens > token_budget_max:
            raise Unsafe(
                reason=f"LLM token budget exceeded: {cumulative_tokens} tokens > {token_budget_max} max"
            )

    # If all budgets are OK, return state unchanged
    return state
