"""Shared type alias for the async node functions the graph wires together."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from langgraph.types import Command

from omniagent.kernel.state import OmniState

GraphNode = Callable[[OmniState], Coroutine[Any, Any, Command[str]]]
