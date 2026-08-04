# 0004: DuckDB as the primary, fully-exercised engine

## Status

Accepted. Postgres conformance remains an open gap, not abandoned.

## Context

The `EngineAdapter` port needs a real, fully-exercised implementation, and
ideally two to prove the port generalizes. DuckDB runs embedded, needs no
server, and is fast enough for this project's data scale (thousands to low
millions of rows per pack). Postgres is the more common production target
but needs a live server this sandbox does not have.

## Decision

`adapters/engine/duckdb.py` is the fully-exercised implementation: every
governed query, every fallback query, every gate test, and the whole
evaluation harness run against it. `adapters/engine/postgres.py` is written
to the complete `EngineAdapter` Protocol, including `normalize_error`, with
a conformance suite that is skipped (not deleted, not faked) when no
`DATABASE_URL` is configured.

## Consequences

Nothing in this codebase can currently claim Postgres works from a passing
test; it can only claim the code exists and type-checks. The honest signal
here is the skip reason in the conformance suite, not a false green. Anyone
deploying against Postgres should run that suite against a real server
before trusting it, not take this ADR as proof it already has been.
