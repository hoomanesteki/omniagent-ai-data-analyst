# 0003: NativeYAML as the primary semantic provider

## Status

Accepted. dbt/MetricFlow as a second provider remains an open gap, not
abandoned.

## Context

The `SemanticProvider` port needs at least one full, real implementation to
prove it is a genuine abstraction and not a shape fitted to a single
library. Two realistic candidates exist: a self-contained YAML dialect this
project defines and compiles itself, or dbt's MetricFlow, an external,
widely-used semantic layer with its own compiler.

## Decision

Build `adapters/semantic/native_yaml.py` as the primary, fully-exercised
provider: pack metrics, dimensions, and joins declared in plain YAML,
compiled to SQL entirely in-process, no subprocess, no external compiler
version to track. Both shipped packs (e-commerce, SaaS) run through it
end to end, including every metric times every categorical dimension
combination, actually executed against real data (see
[0011](0011-backwards-generated-golden-set.md)). A `MetricFlowProvider`
proving the port against real `dbt-metricflow` remains open.

## Consequences

The project has exactly one production-quality semantic provider today,
not two, so the `SemanticProvider` Protocol's real portability is
unverified until a second implementation lands. NativeYAML's simplicity
(no subprocess, no external version drift) made it the right default for a
local-first deployment, but the gap is tracked honestly rather than papered
over with a stub that returns plausible-looking but unverified SQL.
