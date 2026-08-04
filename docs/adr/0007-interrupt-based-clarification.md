# 0007: `interrupt()`-based clarification with a durable checkpointer

## Status

Accepted

## Context

A question that is genuinely ambiguous (two metrics tied on the same
phrase, a router unsure of intent) needs to ask the user something before
continuing, then resume the same turn once answered rather than starting
over. LangGraph offers `interrupt()`, which raises a `GraphInterrupt` that
pauses a run mid-node and can be resumed with `Command(resume=answer)`,
re-entering the same node from its start. This only works with a real
checkpointer persisting state between the pause and the resume; without
one, a paused run's state is gone.

## Decision

`agents/clarify.py` pauses via `interrupt()` rather than ending the turn
with a plain "please clarify" response. `scripts/serve.py` wires a real
checkpointer into every dataset's graph. `AnswerEnvelope` carries a
`resumable: bool` field distinguishing a genuinely paused interrupt
(answer via `/resume`) from a plain non-paused clarification that already
ended the turn (answer via `/ask` on the same thread), since both share
`kind="clarification"` and a client cannot otherwise tell them apart.

The checkpointer is `AsyncSqliteSaver`, not the plain synchronous
`SqliteSaver` first used when this decision was made: `SqliteSaver` does
not implement its async methods at all, so a real `uvicorn`-served
`/ask` call (`ainvoke`, `aget_state`) raised `NotImplementedError` on the
very first request, a bug that every test using the async-native
`InMemorySaver` was structurally unable to catch and that only surfaced
when Phase 11's Docker packaging work finally ran the real composition
root end to end. `AsyncSqliteSaver` in turn only works correctly if its
`aiosqlite` connection is opened and used from the same asyncio event loop
for its entire lifetime; opening it synchronously before `uvicorn.run()`
starts its own loop hangs the first request instead of erroring, since the
connection's background worker thread posts results back onto a loop that
already stopped running. `scripts/serve.py`'s `open_checkpointer` async
context manager exists specifically to keep the connection's lifetime
pinned to one loop, opened from a FastAPI `lifespan` for the REST API and
from a single top-level `asyncio.run()` for the MCP server.

## Consequences

A clarification round-trip resumes exactly where it paused, including
whatever the graph had already computed before the ambiguity was hit, not
a restart. This durability requirement is also what surfaced
[0008](0008-state-reducer-discipline.md): a checkpointer that persists
state across separate `/ask` calls on the same thread exposes reducer bugs
that a stateless, one-shot graph invocation never would.
