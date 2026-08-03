"""Storage ports: vectors, results, verified queries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class Namespace:
    """Namespaced storage key."""

    kind: str  # "schema" | "verified" | "values" | "glossary" | "docs"
    scope: Any  # Scope


@dataclass(frozen=True)
class VerifiedQuery:
    """Approved question-to-query pair."""

    question: str
    artifact: str | dict[str, Any]  # AST or raw SQL
    result_signature: str
    status: str  # "proposed" | "approved" | "trusted"
    approved_by: str
    created_at: datetime


class VectorStore(Protocol):
    """Embedding vector store."""

    def upsert(self, ns: Namespace, docs: Sequence[Any]) -> None:
        """Insert or update vectors."""
        ...

    def search(
        self, ns: Namespace, query_vec: Any, k: int, where: dict[str, Any] | None = None
    ) -> list[Any]:
        """Search by similarity."""
        ...

    def drop(self, ns: Namespace) -> None:
        """Delete namespace."""
        ...


class ResultStore(Protocol):
    """Ephemeral result table storage."""

    def put(self, table: Any, *, principal: Any, ttl_s: int = 900) -> str:
        """Store result, return reference handle."""
        ...

    def get(self, ref: str, *, principal: Any) -> Any:
        """Retrieve result by reference."""
        ...


class VerifiedQueryStore(Protocol):
    """Approved queries for retrieval."""

    def add(self, scope: Any, item: VerifiedQuery) -> None:
        """Store a verified query."""
        ...

    def retrieve(
        self, scope: Any, question: str, k: int = 5, min_status: str = "approved"
    ) -> list[VerifiedQuery]:
        """Retrieve by semantic similarity."""
        ...

    def invalidate(self, tenant: str, dataset: str, older_than_version: str) -> int:
        """Invalidate by schema version, return count."""
        ...
