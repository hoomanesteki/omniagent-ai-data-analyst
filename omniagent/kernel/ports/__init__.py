"""Ports: vendor-agnostic protocols for adapters."""

from .engine import (
    EngineAdapter,
    EngineCapabilities,
    EngineError,
    ReadOnlyMode,
    ResultTable,
)
from .grounding import DocumentEvidence, Evidence, GroundingChecker, GroundingVerdict, TabularEvidence
from .identity import Principal, Scope
from .llm import LLMProvider, ModelCapabilities
from .semantic import (
    CompiledQuery,
    Filter,
    FilterOp,
    SemanticCapabilities,
    SemanticIssue,
    SemanticProvider,
    SemanticQuery,
)
from .stores import Namespace, ResultStore, VerifiedQuery, VerifiedQueryStore, VectorStore
from .time import CalendarSpec, TimeRange, TimeResolver

__all__ = [
    "EngineAdapter",
    "EngineCapabilities",
    "EngineError",
    "ReadOnlyMode",
    "ResultTable",
    "SemanticCapabilities",
    "SemanticProvider",
    "SemanticQuery",
    "CompiledQuery",
    "Filter",
    "FilterOp",
    "SemanticIssue",
    "LLMProvider",
    "ModelCapabilities",
    "VectorStore",
    "ResultStore",
    "VerifiedQueryStore",
    "Namespace",
    "VerifiedQuery",
    "Principal",
    "Scope",
    "TimeResolver",
    "TimeRange",
    "CalendarSpec",
    "Evidence",
    "TabularEvidence",
    "DocumentEvidence",
    "GroundingChecker",
    "GroundingVerdict",
]
