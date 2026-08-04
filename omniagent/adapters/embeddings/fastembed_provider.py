"""fastembed-backed Embedder: local ONNX inference, no API key, no network call."""

from __future__ import annotations

from collections.abc import Sequence

from fastembed import TextEmbedding

_DIM_BY_MODEL = {
    "BAAI/bge-small-en-v1.5": 384,
}


class FastEmbedProvider:
    """Embedder implementation backed by a local fastembed model."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self._model = TextEmbedding(model_name=model_name)
        self.dim = _DIM_BY_MODEL[model_name]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(list(texts))]
