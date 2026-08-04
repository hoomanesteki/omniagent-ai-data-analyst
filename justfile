set dotenv-load

install:
    uv sync --locked --all-extras --dev

lint:
    uv run ruff check omniagent tests scripts
    uv run ruff format --check omniagent tests scripts
    uv run mypy omniagent/kernel omniagent/agents omniagent/channels omniagent/adapters omniagent/memory omniagent/eval
    uv run import-linter lint

test:
    uv run pytest tests/unit tests/contract tests/component tests/perf -n auto --tb=short

test-all:
    uv run pytest tests -n auto --tb=short

coverage:
    uv run pytest tests/unit tests/contract tests/component tests/perf --cov=omniagent --cov-report=term-missing --cov-report=xml

ci: lint test

eval:
    uv run python scripts/run_eval.py

serve:
    uv run python scripts/serve.py

serve-mcp:
    uv run python scripts/serve_mcp.py

docker-up:
    docker compose up --build

docker-down:
    docker compose down --volumes

help:
    @echo "OmniAgent 2.0 build tasks"
    @echo "  make install    - set up environment"
    @echo "  make lint       - ruff, mypy, import-linter"
    @echo "  make test       - fast tests (unit, contract, component)"
    @echo "  make test-all   - all tests including integration and e2e"
    @echo "  make coverage   - run tests with coverage report"
    @echo "  make ci         - run lint and fast tests (what CI runs)"
    @echo "  make eval       - run the evaluation harness, print the scorecard"
    @echo "  make serve      - run the REST API against real adapters"
    @echo "  make serve-mcp  - run the MCP server against real adapters"
    @echo "  make docker-up  - build and run the full stack via docker compose"
    @echo "  make docker-down - stop the docker compose stack and remove volumes"
