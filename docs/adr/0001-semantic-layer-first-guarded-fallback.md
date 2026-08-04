# 0001: Semantic layer first, guarded SQL fallback second

## Status

Accepted

## Context

A question about tabular data can be answered two ways: match it to a
pre-defined metric in a semantic layer and compile deterministic SQL from a
known-correct template, or have a model write SQL directly against the
schema. The first is fast, auditable, and can never hallucinate a join or a
filter that was not declared. The second covers questions no one anticipated,
at the cost of a model actually writing SQL, which can be wrong in ways a
human has to catch.

## Decision

Every question tries the semantic layer first (`master.py`'s deterministic
catalog match, escalating to `semantic_agent.py`'s single narrow LLM call
for filter and time-phrase extraction only). Only a genuine catalog miss
reaches the guarded fallback (`sql_agent.py`), which generates SQL with
schema linking, a bounded self-correction loop, and the same gate stack the
governed path uses. Neither path ever serves an answer that has not been
executed and checked against real data.

## Consequences

Most questions in a well-modeled domain never touch free-form SQL
generation at all, which is where most of a text-to-SQL system's actual
risk lives. Coverage of genuinely novel questions depends on the fallback,
which is slower (an LLM call, possible retries) and carries a wider error
surface than the semantic path, hence gets the stricter treatment (see
[0005](0005-deterministic-gate-stack.md)). A question phrased ambiguously
between "matches a known metric" and "needs the fallback" is resolved by the
router (see [0002](0002-gated-autonomy-deterministic-routing.md)), not by
either path guessing on its own.
