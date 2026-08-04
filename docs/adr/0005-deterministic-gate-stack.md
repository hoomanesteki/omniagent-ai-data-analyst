# 0005: A deterministic, composable gate stack, not an ML guardrail

## Status

Accepted

## Context

Safety for a system that runs generated SQL against real data can be
approached two ways: train or prompt a model to judge whether a query is
safe, or write explicit, deterministic checks for the specific failure
modes that matter (destructive statements, unbounded row counts, PII
leakage, an empty result being narrated as a confident number). A model
judge is flexible but can be argued with, jailbroken, or simply wrong in a
way that is hard to reproduce; a deterministic check either fires or it
does not, every time, on the same input.

## Decision

Eight independent, deterministic gates (`sql_allowlist`, `row_cap`,
`timeout`, `empty_result`, `numeric_recompute`, `pii_mask`, `provenance`,
`llm_budget`) compose into a `GuardrailPolicy` that runs every gate, not
just the first that fails, for a complete audit trail, then raises once if
any violated. The policy runs twice around execution: pre-execution
(catching what can be judged from the SQL text and plan alone) and
post-execution (catching what only real results reveal, like an
unexpectedly empty set or a masked column that leaked). Both the governed
path and the guarded fallback run through the exact same policy instance
shape, not two different safety implementations.

## Consequences

No gate can be bypassed by a clever prompt, because gates do not read model
output as instructions, only as data to check. The tradeoff is coverage:
a deterministic gate only catches what it was explicitly written to catch,
so a genuinely novel failure mode needs a new gate, not a policy tweak. Red
team cases (`eval/redteam.py`) exist specifically to keep proving refusal is
the gate stack's doing, not incidental model reluctance.
