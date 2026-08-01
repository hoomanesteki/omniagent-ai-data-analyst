"""Engine adapter: read-only SQL execution."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, Sequence


class ReadOnlyMode(Enum):
    """Engine-enforced read-only guarantees."""

    NATIVE = "native"  # engine level read only session
    ROLE = "role"  # SELECT only database role
    VALIDATED_ONLY = "validated"  # no engine guarantee, parser is the wall


@dataclass(frozen=True)
class EngineCapabilities:
    """Engine features and constraints."""

    dialect: str
    readonly: ReadOnlyMode
    supports_timeout: bool
    supports_cancel: bool


@dataclass(frozen=True)
class ResultTable:
    """Result set with Arrow interchange contract."""

    columns: tuple[str, ...]
    arrow_schema: Any
    batches: Any
    row_count: int
    truncated: bool
    elapsed_ms: int


class EngineError(Exception):
    """Normalized engine error for repair."""

    code: str
    message: str

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class EngineAdapter(Protocol):
    """Read-only SQL engine interface."""

    def capabilities(self) -> EngineCapabilities:
        """Engine features and constraints."""
        ...

    def execute(
        self,
        sql: str,
        *,
        principal: Any,
        timeout_s: float,
        row_cap: int,
    ) -> ResultTable:
        """Execute read-only SELECT, respecting timeout and row cap."""
        ...

    def schema_snapshot(self, dataset_id: str) -> dict[str, Any]:
        """Table and column metadata for schema linking."""
        ...

    def normalize_error(self, exc: Exception) -> EngineError:
        """Convert vendor error to normalized code."""
        ...
