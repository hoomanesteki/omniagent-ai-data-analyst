"""Fake LLM for testing: ScriptedLLM replays canned responses."""

from typing import Any, Iterator, Optional

from pydantic import BaseModel

from omniagent.kernel.ports.llm import LLMProvider, ModelCapabilities


class ScriptedLLM(LLMProvider):
    """Deterministic LLM that replays a script of canned responses."""

    name = "fake-scripted"

    def __init__(self, script: list[Any], *, max_calls: int = 16):
        """Initialize with a script of responses (BaseModel instances or strings)."""
        self._script = list(script)
        self._max_calls = max_calls
        self.calls: list[dict[str, Any]] = []
        self._schema: Optional[type[BaseModel]] = None

    def with_structured_output(self, schema: type[BaseModel]) -> "ScriptedLLM":
        """Configure expected schema for structured output."""
        self._schema = schema
        return self

    def capabilities(self, model_id: str) -> ModelCapabilities:
        """Fake capabilities."""
        return ModelCapabilities(
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
            tok_per_sec_est=999,  # infinite, no real calls
            price_in_per_mtok=0.0,
            price_out_per_mtok=0.0,
            privacy="local",
        )

    def complete(self, model_id: str, req: dict[str, Any]) -> dict[str, Any]:
        """Replay next scripted response."""
        if len(self.calls) >= self._max_calls:
            raise AssertionError(f"LLM budget {self._max_calls} exceeded")
        self.calls.append({"model": model_id, "req": req})
        if not self._script:
            raise AssertionError(f"LLM called {len(self.calls)}x, script exhausted")
        return self._script.pop(0)

    def structured(
        self, model_id: str, req: dict[str, Any], schema: type[BaseModel]
    ) -> BaseModel:
        """Replay next scripted response, validate schema."""
        if len(self.calls) >= self._max_calls:
            raise AssertionError(f"LLM budget {self._max_calls} exceeded")
        self.calls.append({"model": model_id, "req": req, "schema": schema.__name__})
        if not self._script:
            raise AssertionError(f"LLM called {len(self.calls)}x, script exhausted")
        out = self._script.pop(0)
        if isinstance(out, BaseModel) and not isinstance(out, schema):
            raise AssertionError(
                f"Scripted {type(out).__name__} but request expected {schema.__name__}"
            )
        return out

    def stream(self, model_id: str, req: dict[str, Any]) -> Iterator[str]:
        """Streaming not supported in fake."""
        raise NotImplementedError("ScriptedLLM does not support streaming")

    def health(self) -> bool:
        """Always healthy."""
        return True

    # Test helpers
    def assert_call_count(self, n: int) -> None:
        """Assert that exactly n calls were made."""
        if len(self.calls) != n:
            raise AssertionError(f"Expected {n} calls, got {len(self.calls)}")

    def assert_never_saw(self, needle: str) -> None:
        """Assert that a string never appeared in any call."""
        for call in self.calls:
            req_str = str(call.get("req", ""))
            if needle in req_str:
                raise AssertionError(f"Found '{needle}' in call: {call}")
