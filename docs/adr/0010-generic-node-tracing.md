# 0010: Node tracing wraps the graph generically, not per-node

## Status

Accepted

## Context

Recording a span per graph node (name, duration, masked input, error or
pause status) could be implemented by adding tracing calls inside each
node function, or by wrapping every node at graph-construction time with a
shared function that does the recording once. Instrumenting each node
individually means every future node author must remember to add tracing
correctly, including the specific distinction that a `GraphInterrupt` from
`agents/clarify.py` pausing mid-turn is a deliberate, successful
control-flow event, not an error, and must record as paused rather than
failed.

## Decision

`kernel/telemetry.py`'s `Tracer` is applied through a single `_traced(name,
node_fn, tracers)` wrapper inside `agents/graph.py`'s `build_governed_graph`,
around every `graph.add_node()` call. No node's own code changes to gain
tracing. The wrapper catches `GraphInterrupt` separately from a generic
`Exception` so pausing is never misrecorded as a failure.

## Consequences

Adding a new node to the graph gets tracing for free with zero additional
code in that node. The tradeoff is that a node cannot easily add
node-specific structured fields to its own span without the wrapper
growing a way to accept them; none has needed to yet, and this ADR should
be revisited if one does.
