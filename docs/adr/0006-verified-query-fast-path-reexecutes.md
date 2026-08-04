# 0006: Verified-query fast path always re-executes, never serves a cached value

## Status

Accepted

## Context

Once a fallback-generated SQL query has been thumbs-upped, later
paraphrases of the same question could either replay the stored result
directly (fastest, but stale the moment underlying data changes) or replay
the stored SQL artifact against current data (slightly slower, always
correct as of now). A cosine-similarity match against stored questions is
also not precise enough on its own to gate this decision: measured against
the real embedder this project uses, a same-shape but wrong-metric near
miss ("total revenue by region" against a stored "total customers by
region") scored higher than some genuine paraphrases of unrelated
questions.

## Decision

`agents/fast_path.py` treats a verified-query hit as "skip SQL generation,"
never as "skip execution." The stored SQL artifact is re-run through the
real engine and the full `GuardrailPolicy` on every hit. The fast path's
store is constructed with a much stricter similarity floor (~0.9+) than the
store's general-retrieval default (0.5), since "trust this artifact enough
to skip writing new SQL" is a materially higher bar than "surface this as a
candidate for something else to review."

## Consequences

A verified query can never go stale in a way that silently returns wrong
numbers; a schema change or data update is reflected on the very next hit.
The cost is that a fast-path hit is not free: it still pays for one real
query execution and one full gate pass, just not a model call. Embedding
similarity is used strictly as a candidate-ranking signal feeding a
deterministic threshold, never as a standalone safety decision, consistent
with [0005](0005-deterministic-gate-stack.md).
