# 0008: Per-turn state fields default to no reducer

## Status

Accepted

## Context

LangGraph state fields can declare a reducer (`Annotated[list, add]`) so
multiple writes across a run accumulate instead of overwrite. `messages`
genuinely needs this: conversation history must grow across turns. Other
list fields on `OmniState`, like `assumptions` and `sql_candidates`, were
given the same reducer on the assumption that "more than one node might add
to this," without distinguishing accumulation within one turn from
accumulation across turns.

That distinction did not matter with no checkpointer, since every `/ask`
call was a fully independent graph run and any field reset to empty every
time regardless of its reducer. Once [0007](0007-interrupt-based-clarification.md)
wired a real checkpointer so state persists across separate `/ask` calls
on the same thread, the `add` reducer kept concatenating: a later, unrelated
question still carried the previous turn's assumption text forward.

## Decision

A state field only gets the `add` reducer if it must survive past the end
of the current turn (`messages` is the only field that does). Every other
accumulating field is a plain field with no reducer, and each node that
contributes to it returns the full current value, not a delta, following
the convention `llm_calls`/`model_calls_by_node` already used elsewhere:
`working.assumptions = list(state.assumptions) + [new_one]`, returned whole.

## Consequences

Any new field added to `OmniState` must be checked against this question
before deciding its reducer, not defaulted to `add` because that is what a
nearby field happens to use. The bug this decision fixes was caught by a
differentiated-content test (each turn's fake node returns a distinguishable
string); an earlier version of the same test used identical constant
strings across turns and produced a false "looks fine" result, which is
itself a caution about writing test fixtures that happen to be
symmetric in the one dimension that would expose the bug.
