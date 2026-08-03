"""Ollama LLM provider adapter (local or remote)."""

import os
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

from omniagent.kernel.ports.llm import LLMProvider, ModelCapabilities


class OllamaProvider(LLMProvider):
    """Ollama LLM provider (local or remote HTTP)."""

    name = "ollama"

    def __init__(self, base_url: str | None = None):
        """Initialize with Ollama base URL (default: http://localhost:11434)."""
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    def capabilities(self, model_id: str) -> ModelCapabilities:
        """Return capabilities for common Ollama models."""
        # Common open models served via Ollama
        capabilities_map = {
            "llama2": ModelCapabilities(
                context_window=4096,
                supports_strict_json_schema=False,
                supports_tools=False,
                supports_parallel_tools=False,
                structured_with_tools=False,
                structured_with_streaming=False,
                prompt_caching="none",
                supports_batch=False,
                reasoning_effort=False,
                supports_lora_adapters=False,
                tok_per_sec_est=50,  # local, CPU-dependent
                price_in_per_mtok=0.0,
                price_out_per_mtok=0.0,
                privacy="local",
            ),
            "mistral": ModelCapabilities(
                context_window=32768,
                supports_strict_json_schema=False,
                supports_tools=False,
                supports_parallel_tools=False,
                structured_with_tools=False,
                structured_with_streaming=False,
                prompt_caching="none",
                supports_batch=False,
                reasoning_effort=False,
                supports_lora_adapters=False,
                tok_per_sec_est=100,
                price_in_per_mtok=0.0,
                price_out_per_mtok=0.0,
                privacy="local",
            ),
            "neural-chat": ModelCapabilities(
                context_window=4096,
                supports_strict_json_schema=False,
                supports_tools=False,
                supports_parallel_tools=False,
                structured_with_tools=False,
                structured_with_streaming=False,
                prompt_caching="none",
                supports_batch=False,
                reasoning_effort=False,
                supports_lora_adapters=False,
                tok_per_sec_est=75,
                price_in_per_mtok=0.0,
                price_out_per_mtok=0.0,
                privacy="local",
            ),
        }
        if model_id not in capabilities_map:
            # Unknown model: return a conservative default
            return ModelCapabilities(
                context_window=4096,
                supports_strict_json_schema=False,
                supports_tools=False,
                supports_parallel_tools=False,
                structured_with_tools=False,
                structured_with_streaming=False,
                prompt_caching="none",
                supports_batch=False,
                reasoning_effort=False,
                supports_lora_adapters=False,
                tok_per_sec_est=50,
                price_in_per_mtok=0.0,
                price_out_per_mtok=0.0,
                privacy="local",
            )
        return capabilities_map[model_id]

    def complete(self, model_id: str, req: dict[str, Any]) -> dict[str, Any]:
        """Completion request (not implemented in scaffold)."""
        raise NotImplementedError("Use langchain-ollama instead")

    def structured(self, model_id: str, req: dict[str, Any], schema: type[BaseModel]) -> BaseModel:
        """Structured output (not implemented in scaffold)."""
        raise NotImplementedError(
            "Use langchain-ollama with prompt engineering for structured output"
        )

    def stream(self, model_id: str, req: dict[str, Any]) -> Iterator[str]:
        """Token stream (not implemented in scaffold)."""
        raise NotImplementedError("Use langchain-ollama with stream=True")

    def health(self) -> bool:
        """Check Ollama server health."""
        try:
            import requests

            resp = requests.get(f"{self.base_url}/api/tags", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False
