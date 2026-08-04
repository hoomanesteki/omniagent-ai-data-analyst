set dotenv-load

install:
    uv sync --locked --all-extras --dev

lint:
    uv run ruff check omniagent tests
    uv run ruff format --check omniagent tests
    uv run mypy omniagent/kernel omniagent/agents omniagent/channels omniagent/adapters omniagent/memory
    uv run import-linter lint

test:
    uv run pytest tests/unit tests/contract tests/component -n auto --tb=short

test-all:
    uv run pytest tests -n auto --tb=short

coverage:
    uv run pytest tests/unit tests/contract tests/component --cov=omniagent --cov-report=term-missing --cov-report=xml

ci: lint test

eval:
    uv run python scripts/run_eval.py

help:
    @echo "OmniAgent 2.0 build tasks"
    @echo "  make install    - set up environment"
    @echo "  make lint       - ruff, mypy, import-linter"
    @echo "  make test       - fast tests (unit, contract, component)"
    @echo "  make test-all   - all tests including integration and e2e"
    @echo "  make coverage   - run tests with coverage report"
    @echo "  make ci         - run lint and fast tests (what CI runs)"
    @echo "  make eval       - run the evaluation harness, print the scorecard"
