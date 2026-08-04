# Architecture Decision Records

Each record captures a decision that shaped OmniAgent 2.0's design and would
otherwise only live in commit history or memory. Format: context, decision,
consequences. Superseding a decision means adding a new record and marking
the old one superseded, not editing history.

- [0001](0001-semantic-layer-first-guarded-fallback.md) - Semantic layer first, guarded SQL fallback second
- [0002](0002-gated-autonomy-deterministic-routing.md) - Gated autonomy: deterministic routing, narrow LLM calls
- [0003](0003-native-yaml-primary-semantic-provider.md) - NativeYAML as the primary semantic provider
- [0004](0004-duckdb-primary-engine.md) - DuckDB as the primary, fully-exercised engine
- [0005](0005-deterministic-gate-stack.md) - A deterministic, composable gate stack, not an ML guardrail
- [0006](0006-verified-query-fast-path-reexecutes.md) - Verified-query fast path always re-executes, never serves a cached value
- [0007](0007-interrupt-based-clarification.md) - `interrupt()`-based clarification with a durable checkpointer
- [0008](0008-state-reducer-discipline.md) - Per-turn state fields default to no reducer
- [0009](0009-composition-roots-outside-package.md) - Composition roots live outside the `omniagent` package
- [0010](0010-generic-node-tracing.md) - Node tracing wraps the graph generically, not per-node
- [0011](0011-backwards-generated-golden-set.md) - Golden sets are generated backwards from real execution
- [0012](0012-mcp-mirrors-rest-no-raw-sql.md) - MCP is a thin transport mirror of the REST channel, with no raw-SQL tool
