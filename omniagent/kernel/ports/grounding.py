"""Grounding: verify claims against evidence."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class TabularEvidence:
    """Result table evidence."""

    result_ref: str
    computed: dict[str, float]
    provenance: dict[str, Any]


@dataclass(frozen=True)
class DocumentEvidence:
    """Retrieved document passages."""

    passages: tuple[Any, ...]
    provenance: dict[str, Any]


Evidence = TabularEvidence | DocumentEvidence


@dataclass(frozen=True)
class GroundingVerdict:
    """Grounding check result."""

    is_grounded: bool
    reason: str | None = None


class GroundingChecker(Protocol):
    """Verify claims against evidence."""

    def check(self, claim: str, evidence: Evidence) -> GroundingVerdict:
        """Verify claim is grounded in evidence."""
        ...
