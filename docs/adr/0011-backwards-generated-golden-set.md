# 0011: Golden sets are generated backwards from real execution

## Status

Accepted

## Context

An evaluation golden set can be authored by hand (a human writes the
expected SQL and answer for each question) or generated backwards: for
every metric and dimension combination a catalog actually knows, compile
the real query, execute it against the real warehouse, and use that
execution's result as ground truth, then attach template phrasings of the
question afterward. Hand-authored sets drift from the pack YAML and the
warehouse the moment either changes, and are also the more common source of
evaluation bugs (a human's expected answer being wrong, not the system's).

## Decision

`eval/goldgen.py`'s `generate_golden_set` enumerates every metric the
catalog knows (plus one valid breakdown dimension per metric), compiles
and executes each against the real engine, and captures the executed SQL
and result as ground truth. Nothing is checked into the repository as
static golden data; a golden set is regenerated fresh every evaluation run
directly from the current pack YAML and warehouse.

## Consequences

A golden set can never silently drift out of sync with the packs or
warehouse it is generated from, and this generation step itself doubles as
an execution test: it is what caught a real join-path bug in
`native_yaml.py` (a two-hop join spliced in an unrelated model's join type
and condition instead of the one that actually applied to that edge),
since `compile()` alone never runs its own SQL. The tradeoff is that a
golden set's coverage is
bounded by what the catalog already declares; a question style the catalog
has no metric for is not exercised by this generator and needs the red
team or manual test suites instead.
