# 0012: MCP is a thin transport mirror of the REST channel, with no raw-SQL tool

## Status

Accepted

## Context

An MCP server for this project could expose a new, MCP-specific set of
capabilities, or it could expose exactly the same capabilities the REST API
already exposes, over a different transport. The project's standing rule
is that no channel gets a capability another channel lacks: a human using
the Streamlit UI and an agent using MCP should be bound by the same gates.
The most direct way to violate that rule by accident is to give an MCP
client something convenient for automation but never offered to a human,
like a tool that runs arbitrary SQL against the warehouse.

## Decision

`channels/mcp_server.py` exposes exactly four tools:
`list_datasets`, `ask`, `resume`, `feedback`, matching the REST API's
`/datasets`, `/ask`, `/resume`, `/feedback` one to one. There is
deliberately no raw-SQL tool. Both channels are built over the same
`DatasetRuntime` objects and share `record_turn` and `result_to_envelope`
from `channels/service.py` rather than each implementing their own
ledger-recording, tracer-cleanup, or envelope-construction logic, so the
two channels cannot quietly drift into different behavior for the same
underlying turn.

## Consequences

An MCP client is bound by exactly the same gate stack, router, and
clarification flow a human gets; a destructive query attempted through MCP
is refused for the same reason it would be refused through the UI, since
both paths ultimately call the same guarded `sql_agent`. The cost is that
MCP cannot offer anything REST does not, which is the point; a future tool
idea that seems MCP-specific should first be asked whether it belongs on
the REST API too, not added to MCP alone.
