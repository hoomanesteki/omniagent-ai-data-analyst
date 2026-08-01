"""LLM provider: model capabilities and inference."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelCapabilities:
    """Model feature flags and constraints."""

    context_window: int
    supports_strict_json_schema: bool
    supports_tools: bool
    supports_parallel_tools: bool
    structured_with_tools: bool
    structured_with_streaming: bool
    prompt_caching: str  # "auto" | "explicit" | "none"
    supports_batch: bool
    reasoning_effort: bool
    supports_lora_adapters: bool
    tok_per_sec_est: int
    price_in_per_mtok: float
    price_out_per_mtok: float
    privacy: str  # "local" | "private-cloud" | "shared-api"


class LLMProvider(Protocol):
    """Language model provider interface."""

    name: str

    def capabilities(self, model_id: str) -> ModelCapabilities:
        """Model feature flags."""
        ...

    def complete(self, model_id: str, req: dict[str, Any]) -> dict[str, Any]:
        """Completion request."""
        ...

    def structured(
        self, model_id: str, req: dict[str, Any], schema: type
    ) -> Any:
        """Structured output."""
        ...

    def stream(self, model_id: str, req: dict[str, Any]):
        """Token stream."""
        ...

    def health(self) -> bool:
        """Provider health check."""
        ...
