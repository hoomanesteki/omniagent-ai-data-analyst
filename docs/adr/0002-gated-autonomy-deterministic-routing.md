# 0002: Gated autonomy: deterministic routing, narrow LLM calls

## Status

Accepted

## Context

An agentic system can let a model decide freely what to do at each step, or
constrain it to a fixed decision structure where a model only fills in
specific, narrow gaps. Free-roaming agentic control is more flexible but
harder to audit, test, or bound the failure modes of; a model deciding "what
happens next" is also a model deciding when to skip a safety check.

## Decision

OmniAgent's graph is a fixed decision tree, not a model-driven loop:
deterministic catalog match, then (only on a miss) one narrow-purpose LLM
call to route intent, then either deterministic compilation or a bounded
self-correcting SQL generation loop, then the gate stack, then deterministic
narration and chart selection. A model is never asked "what should happen
next in the graph"; it is asked single, scoped questions ("does this phrase
name a known metric filter," "is this SQL safe to attempt") whose answers
feed a graph edge a human already designed.

## Consequences

Every LLM call in the system has one job and a typed, validated output
(see `kernel/models.py`'s Pydantic contracts), which makes call-count and
behavior assertions possible in tests (`ScriptedLLM.assert_call_count`) and
keeps the token budget predictable per turn. The tradeoff is less
flexibility: a genuinely novel interaction pattern needs a new graph edge
written by a human, not a model improvising one. This is a deliberate,
standing constraint, not a placeholder for a future "more autonomous"
version; it should be preserved as new capability (Phase 6's router, Phase 5's
fallback) is added, not loosened for convenience.
