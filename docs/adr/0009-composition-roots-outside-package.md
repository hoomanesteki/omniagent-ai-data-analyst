# 0009: Composition roots live outside the `omniagent` package

## Status

Accepted

## Context

`.importlinter`'s layering contract declares `omniagent.channels` and
`omniagent.adapters` as parallel top-level layers that must not import each
other, so the library itself never depends on which concrete adapter
(Groq, DuckDB, NativeYAML) a deployment chooses. Something still has to
construct those concrete adapters and hand them to a channel, and that
something necessarily imports across both layers. Placing it inside
`omniagent.channels` was tried first and import-linter caught the violation
immediately.

## Decision

Every composition root (`scripts/serve.py` for the REST API,
`scripts/serve_mcp.py` for the MCP server, `scripts/run_eval.py` for the
evaluation harness) lives outside the `omniagent` package entirely,
alongside the data-generation and warehouse-loading scripts that already
sat there for the same operational-entrypoint reason.

## Consequences

`omniagent` stays a library that is fully usable, testable, and
type-checkable without ever knowing how any one deployment wires it up.
The cost is a small amount of duplication between composition roots that
build similar sets of adapters for different channels (`serve.py` and
`serve_mcp.py` both build the same `DatasetRuntime` shape); this is judged
worth it rather than introducing a shared adapter-wiring module that would
itself need to live somewhere and would blur which layer owns adapter
construction.
