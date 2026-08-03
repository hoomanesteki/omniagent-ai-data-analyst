"""Safety gate exceptions."""


class Unsafe(Exception):  # noqa: N818 - established gate-stack vocabulary, not merely an error
    """Exception raised when a safety gate detects unsafe state or action."""

    def __init__(self, reason: str) -> None:
        """Initialize Unsafe exception with a reason."""
        self.reason = reason
        super().__init__(reason)
