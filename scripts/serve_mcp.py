#!/usr/bin/env python3
# ruff: noqa: T201
"""Composition root for the MCP channel: the exact same dataset runtimes
`scripts/serve.py` builds for the REST API, handed to
`omniagent.channels.mcp_server.build_mcp_server` instead of
`omniagent.channels.service.create_app`. Lives outside omniagent/ for the
same layering reason as scripts/serve.py.

Usage:
    export GROQ_API_KEY=...
    python scripts/serve_mcp.py                          # stdio, for an
                                                           # IDE/agent client
                                                           # that spawns this
                                                           # process directly
    python scripts/serve_mcp.py --transport streamable-http --port 8100
"""

from __future__ import annotations

import argparse
import asyncio

from omniagent.channels.mcp_server import build_mcp_server
from scripts.serve import build_default_datasets, open_checkpointer


async def _run(args: argparse.Namespace) -> None:
    # The checkpointer's background worker must be opened and used from the
    # same event loop for its whole lifetime (see open_checkpointer's own
    # docstring in scripts/serve.py), so building datasets and running the
    # server both happen inside this one `asyncio.run()`, not split across
    # a sync build step and a separate `server.run()` call that would open
    # its own loop via anyio.
    async with open_checkpointer("data/warehouse/mcp_checkpoints.sqlite") as checkpointer:
        server = build_mcp_server(build_default_datasets(checkpointer=checkpointer))
        if args.transport == "stdio":
            await server.run_stdio_async()
        else:
            await server.run_streamable_http_async(host=args.host, port=args.port)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OmniAgent MCP server.")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container-facing by design
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
