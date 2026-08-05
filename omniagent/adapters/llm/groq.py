"""Groq LLM provider adapter."""

import os
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

from omniagent.adapters.llm.prompting import build_prompt
from omniagent.kernel.ports.llm import LLMProvider, ModelCapabilities


class GroqProvider(LLMProvider):
    """Groq Cloud LLM provider."""

    name = "groq"

    def __init__(self, api_key: str | None = None):
        """Initialize with API key from environment or parameter."""
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not set and no api_key provided")

    def capabilities(self, model_id: str) -> ModelCapabilities:
        """Return capabilities for a Groq model."""
        # Groq models as of 2026-08: gpt-oss-120b, gpt-oss-20b, llama-3.3-70b, llama-3.1-8b
        capabilities_map = {
            "openai/gpt-oss-120b": ModelCapabilities(
                context_window=131072,
                supports_strict_json_schema=True,
                supports_tools=False,
                supports_parallel_tools=False,
                structured_with_tools=False,
                structured_with_streaming=False,
                prompt_caching="auto",
                supports_batch=True,
                reasoning_effort=False,
                supports_lora_adapters=False,
                tok_per_sec_est=500,
                price_in_per_mtok=0.15,
                price_out_per_mtok=0.60,
                privacy="shared-api",
            ),
            "openai/gpt-oss-20b": ModelCapabilities(
                context_window=131072,
                supports_strict_json_schema=True,
                supports_tools=False,
                supports_parallel_tools=False,
                structured_with_tools=False,
                structured_with_streaming=False,
                prompt_caching="auto",
                supports_batch=True,
                reasoning_effort=False,
                supports_lora_adapters=False,
                tok_per_sec_est=1000,
                price_in_per_mtok=0.075,
                price_out_per_mtok=0.30,
                privacy="shared-api",
            ),
            "llama-3.3-70b-versatile": ModelCapabilities(
                context_window=131072,
                supports_strict_json_schema=True,
                supports_tools=True,
                supports_parallel_tools=True,
                structured_with_tools=False,
                structured_with_streaming=False,
                prompt_caching="auto",
                supports_batch=True,
                reasoning_effort=False,
                supports_lora_adapters=False,
                tok_per_sec_est=400,
                price_in_per_mtok=0.27,
                price_out_per_mtok=0.36,
                privacy="shared-api",
            ),
            "llama-3.1-8b-instant": ModelCapabilities(
                context_window=131072,
                supports_strict_json_schema=True,
                supports_tools=False,
                supports_parallel_tools=False,
                structured_with_tools=False,
                structured_with_streaming=False,
                prompt_caching="auto",
                supports_batch=True,
                reasoning_effort=False,
                supports_lora_adapters=False,
                tok_per_sec_est=1000,
                price_in_per_mtok=0.075,
                price_out_per_mtok=0.10,
                privacy="shared-api",
            ),
        }
        if model_id not in capabilities_map:
            raise ValueError(f"Unknown Groq model: {model_id}")
        return capabilities_map[model_id]

    def complete(self, model_id: str, req: dict[str, Any]) -> dict[str, Any]:
        """Completion request (not implemented in scaffold)."""
        raise NotImplementedError("Use langchain-groq ChatGroq instead")

    def structured(self, model_id: str, req: dict[str, Any], schema: type[BaseModel]) -> BaseModel:
        """Structured extraction call via langchain-groq's JSON-schema mode.

        `req` is a small task-shaped dict (see `_build_prompt`) rather than a
        raw prompt string, so callers stay decoupled from any particular
        provider's prompting conventions.
        """
        from langchain_groq import ChatGroq

        chat = ChatGroq(model_name=model_id, api_key=self.api_key, temperature=0)
        structured_chat = chat.with_structured_output(schema)
        result = structured_chat.invoke(build_prompt(req))
        if not isinstance(result, schema):
            # with_structured_output can return a dict depending on method;
            # normalize defensively rather than trust the return type alone.
            result = schema.model_validate(result)
        return result

    def stream(self, model_id: str, req: dict[str, Any]) -> Iterator[str]:
        """Token stream (not implemented in scaffold)."""
        raise NotImplementedError("Use langchain-groq with stream=True")

    def health(self) -> bool:
        """Check provider health."""
        return bool(self.api_key)
