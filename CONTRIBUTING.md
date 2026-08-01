# Contributing to OmniAgent 2.0

## Commit Message Format

OmniAgent uses Conventional Commits for a human-readable, machine-parseable changelog.

### Format

```
<type>(<scope>): <short summary, <= 70 chars, no period>

<body, 72-char wrap, plain English, state what and why>

<footer, any co-authors or issue references>
```

### Type

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation only
- `test:` test additions or fixes
- `ci:` CI/CD changes
- `chore:` build, deps, housekeeping
- `refactor:` logic restructure, no behavior change
- `perf:` performance improvement
- `prompt:` prompt tuning or templates
- `semantic:` semantic model changes
- `eval:` golden set or evaluation fixtures

### Scope

The package or system being changed, e.g., `kernel`, `adapters/engine`, `eval/judge`.

### Examples

```
feat(kernel/ports): add semantic provider protocol

Defines the Protocol contract for metrics engines. Declares methods for
catalog(), validate(), compile(), and capabilities(). This is the vendor-
neutral abstraction layer that lets us swap MetricFlow for Cube later.

Co-Authored-By: Hooman Esteki <esteki.net@gmail.com>
```

```
fix(adapters/engine): normalize DuckDB errors before repair

The self-correction loop fed raw vendor strings to the model, which
coupled prompts to DuckDB's specific wording. Now we normalize to
error codes (table_not_found, constraint_violation, etc.) so the
repair prompt is portable.
```

## Branch Naming

- `build/<feature>`: building a feature, e.g., `build/omniagent-2.0`
- `fix/<issue>`: bug fix, e.g., `fix/critical-wrong-number`
- `docs/<topic>`: documentation, e.g., `docs/architecture-adrs`

All feature work happens on explicit branches. Merge to `main` with a pull request and a human approval (once CI lands).

## Before Pushing

```bash
make install    # set up environment
make lint       # ruff, mypy, import-linter
make test       # unit + property + contract
```

These gates also run in CI. Failing locally means the PR will fail CI.

## Testing Tiers

Write tests in the appropriate tier:

| Tier | When | Tool | Real model | Real DB |
|------|------|------|-----------|---------|
| Unit | pure functions | pytest | no | no |
| Property | invariants | hypothesis | no | no |
| Contract | adapter impl | pytest + abstract suite | no | no |
| Component | single node | pytest + ScriptedLLM | no | no |
| Integration | graph flows | pytest + DuckDB | no | yes |
| E2E | question to card | pytest + cassettes | no | no |
| Eval | accuracy | eval.run_eval | yes | yes |

See `09_MLOPS_CICD_CT.md` for the detailed pyramid.

## Code Style

- **Ruff** enforces line length, import ordering, naming, and security rules.
- **MyPy** strict mode on kernel and agents; any `# type: ignore` requires a reason comment.
- **No vendor imports in kernel:** `kernel/` and all `ports/` must import only Python std lib and Pydantic. Adapters live in `adapters/`.
- **Type annotations always:** every function parameter and return must be annotated.
- **Docstrings:** module docstring required; function docstrings for public APIs.

## Release Process

1. Commits merge to main with Conventional Commits.
2. `release-please` reads commits, bumps semver, generates `CHANGELOG.md`.
3. Release PR is reviewed and merged, which cuts the git tag.
4. CI builds and pushes the container.
5. A human approves deploy to staging, then prod with canary.

See `.github/workflows/release.yml` for details.

## Performance and Cost

Every PR is evaluated on:
- **Execution accuracy** on the golden set (must not regress > 1 point).
- **Latency** (p95 end-to-end; must not exceed SLO).
- **Cost** (tokens per answer; warn if > +30%).
- **Model call count** (must stay within budget).

See `06_PERFORMANCE_AND_COST.md` for SLOs.

## Questions?

Refer to the specification docs in the `docs/` folder:

- `01_BUSINESS_CASE.md`: why this exists
- `02_ARCHITECTURE.md`: system design
- `04_AGENT_GRAPH.md`: graph nodes and edges
- `13_ROADMAP.md`: phase-by-phase build order
