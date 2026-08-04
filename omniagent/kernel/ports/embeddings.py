"""Text embedding port: turns text into dense vectors for semantic search."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):
    """A model that maps text to fixed-dimension dense vectors."""

    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts, returning one vector per input, in order."""
        ...
