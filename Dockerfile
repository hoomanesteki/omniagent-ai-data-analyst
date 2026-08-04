# Single image used by every service in docker-compose.yml (data-init, the
# REST API, the Streamlit UI, the MCP server) -- they differ only in their
# command, not their dependencies, so one build covers all of them and
# nothing drifts between what a governed answer sees running as one
# channel versus another.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm

WORKDIR /app

# Dependencies before source code so a source-only change reuses this layer
# instead of reinstalling everything.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev \
    --extra duckdb --extra groq --extra vectors --extra service --extra mcp --extra streamlit

COPY omniagent ./omniagent
COPY scripts ./scripts
COPY packs ./packs
COPY README.md ./README.md

RUN uv sync --locked --no-dev \
    --extra duckdb --extra groq --extra vectors --extra service --extra mcp --extra streamlit

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000 8100 8501

CMD ["python", "scripts/serve.py", "--host", "0.0.0.0", "--port", "8000"]
