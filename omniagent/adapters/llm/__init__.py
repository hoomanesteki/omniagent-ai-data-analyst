"""LLM adapters: Groq, Ollama, and testing fakes."""

from omniagent.adapters.llm.groq import GroqProvider
from omniagent.adapters.llm.ollama import OllamaProvider

__all__ = ["GroqProvider", "OllamaProvider"]
