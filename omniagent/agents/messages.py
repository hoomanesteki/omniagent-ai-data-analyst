"""Small shared helpers for reading OmniState.messages."""

from __future__ import annotations

from omniagent.kernel.state import OmniState


def latest_user_message(state: OmniState) -> str:
    """The most recent message with role 'user', or '' if there is none."""
    for message in reversed(state.messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            return content if isinstance(content, str) else ""
    return ""
