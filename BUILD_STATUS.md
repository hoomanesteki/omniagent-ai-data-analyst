# OmniAgent 2.0 Build Status

## Completed Phases (merged to `main`)

### Phase 0: Scaffold ✅

- Kernel port Protocols (engine, semantic, LLM, stores, identity, time, grounding)
- Layering enforcement via import-linter
- pyproject.toml with optional extras
- pytest configuration with test pyramid markers
- justfile for common tasks

### Phase 1: Data, Engine, and Semantic Layer ✅

- `scripts/generate_samples.py`, `scripts/load_warehouse.py` for e-commerce and SaaS datasets
- E-commerce and SaaS packs: NativeYAML semantic layer (primary, fully exercised)
- `adapters/engine/duckdb.py` (fully exercised) and `adapters/engine/postgres.py` (written to
  full Protocol, conformance suite skipped without a live Postgres server)
- `adapters/semantic/native_yaml.py` — dbt/MetricFlow as a second provider remains open
- `kernel/catalog.py` (deterministic phrase matching) and `kernel/time_resolver.py`

### Phase 2: Model Provider and Typed Contracts ✅

- `adapters/llm/groq.py`, `adapters/llm/ollama.py` — genuinely functional `structured()`
  implementations via langchain-groq / langchain-ollama, not stubs
- `adapters/llm/prompting.py` — shared task-to-prompt builder across both providers
- All Pydantic contracts in `kernel/models.py` (`Route`, `SqlCandidate`, `SemanticExtraction`, etc.)
- `tests/fakes/llm.py::ScriptedLLM` — the zero-API-key fake every test uses

### Phase 3: Governed Path End-to-End ✅

- `agents/master.py` (deterministic catalog match, no model call)
- `agents/semantic_agent.py` (exactly one LLM call: time phrase + filter extraction)
- `agents/executor.py` (compile, guard, execute, guard again)
- `agents/graph.py` wiring: master → semantic_agent → executor → narrator

### Phase 4: Gate Stack ✅

- All 8 gates: `sql_allowlist`, `row_cap`, `timeout`, `empty_result`, `numeric_recompute`,
  `pii_mask`, `provenance`, `llm_budget`
- `kernel/gates/GuardrailPolicy` — composable, runs every gate (no short-circuit) for a full
  audit trail, then raises once if any violated
- Wired into the executor as two passes: pre-execution (defense in depth) and post-execution

### Phase 5: Guarded Fallback ✅

- `adapters/vectors/duckdb_vss.py` (`DuckDBVSSStore`) — DuckDB + VSS extension, brute-force
  `array_cosine_similarity` (appropriate at this project's scale: hundreds of verified
  queries per tenant, not millions)
- `adapters/embeddings/fastembed_provider.py` — local `BAAI/bge-small-en-v1.5` embeddings,
  no API key, no network at query time
- `memory/verified_queries.py` (`DuckDBVerifiedQueryStore`) — namespaced by
  (tenant, dataset, schema_version); a schema-version bump makes prior entries unreachable
  by construction, `invalidate()` reclaims their storage
- `memory/value_dictionary.py` (`DuckDBValueDictionary`) — grounds free-text filter phrases
  to real, indexed column values
- `agents/sql_agent.py` — schema-linked SQL generation with a bounded self-correction loop
  (retry on any gate or engine rejection, abstain once the budget is exhausted), behind the
  same `GuardrailPolicy` the governed executor uses
- `agents/fast_path.py` — cache-first check against verified queries ahead of `sql_agent`;
  re-executes the cached artifact against current data rather than serving a stale result,
  and uses a much stricter similarity floor than general retrieval before trusting a hit
- Wired as an opt-in attachment to the governed graph (`master → fast_path → sql_agent →
  narrator`) — active only when a `verified_query_store` is supplied to `build_governed_graph`

### Phase 7: Narration & Charts ✅

- `agents/narrator.py` — template-first narration (zero extra LLM calls), deterministic
  confidence formula, conditional-critic decision function
- `agents/charts.py` — deterministic chart-type selection, CVD-safe categorical palette
- `agents/suggester.py` — deterministic follow-up suggestions

### Phase 8: Interface ✅

- `channels/service.py` — FastAPI (`/health`, `/datasets`, `/ask`, `/resume`, `/feedback`)
- `channels/streamlit_app.py` — dataset picker, starter chips, answer cards, feedback,
  clarification handling; consumes only the REST API
- `scripts/serve.py` — composition root (lives outside `omniagent/` — the layering contract
  keeps `channels` and `adapters` as parallel top-level layers)

---

## Remaining Phases

### Phase 6: Routing & Durability

**Deliverables:**
- Router model behind deterministic match
- Clarification node with interrupt()
- Checkpointer (SQLite local, Postgres for scale)
- Resume via Command(resume=...)

**Done When:**

- Governed questions never touch SQL agent (trajectory assertion — already true today,
  since the fallback only attaches on a catalog miss; this phase adds the smarter router
  ahead of that deterministic-first structure, not a replacement for it)
- Ambiguous questions clarify before execution
- Follow-ups use checkpointed context (today's `/resume` is a working but simpler
  in-memory thread-history stand-in, not a real LangGraph checkpointer)

---

### Phase 9: Evaluation

**Deliverables:**
- Semi-automatic golden set generator
- Golden sets for both packs (~60 items each)
- Execution accuracy scorer (normalized comparison)
- Component scorers (route acc, metric-match, schema-link recall, etc.)
- Red team suite (deterministic subset in CI)
- eval.run_eval.py and CI workflow

**Done When:**
- `make eval` prints full scorecard
- CI fails on regressions and all red team failures
- Bootstrap CIs on all metrics
- Paired comparison gates (McNemar)

---

### Phase 10: MLOps and Observability

**Deliverables:**

- Tracing spans on every node (inputs masked)
- Answer ledger table (durable audit record)
- Hermetic performance tests (on every PR, free)
- Release automation (conventional commits, semver)
- Continuous tuning pipeline skeleton
- Nightly performance smoke

**Done When:**
- Turns emit traces with masked inputs
- PR pipeline completes in < 10 minutes
- Nightly smoke compares against baseline
- Metrics gate regressions

---

### Phase 11: MCP and Packaging

**Deliverables:**
- MCP server with discovery, query, ask, feedback tools
- Dockerfile and docker-compose
- README with scorecard first
- Architecture decision records

**Done When:**
- External MCP client can call governed queries
- Destructive SQL is refused identically to UI
- `docker compose up` reproduces correct answer in < 5 min

---

### Phase 12: Demo and Pilot Kit

**Deliverables:**
- 90-second demo (raw vs governed, answer card, clarification, trap, MCP reveal, scorecard)
- Reproducible comparison chart (text-to-SQL vs governed)
- Pilot runbook

**Done When:**
- Demo runs end-to-end
- Scorecard generated from script (not hand-assembled)
- README leads with numbers

---

## Overall Roadmap

**Critical Path:** 0 → 1 → 3 → 4 → 5 → 6 → 7 → 8 → 9 (5 and 6 not yet in that literal order —
5 landed ahead of 6, since 6 depends on 5's fallback existing before a router can sit in front
of it; this does not change 6's own scope)

**Minimum MVP (complete):** Phases 0, 1, 3, 4, 7, 8 on e-commerce and SaaS.

**Also complete beyond MVP:** Phase 2 (real LLM adapters), Phase 5 (guarded fallback).

**Still open:** dbt/MetricFlow as the semantic layer's second provider (NativeYAML is the
fully-exercised primary); Postgres engine conformance (written, skipped without a live server);
Phases 6, 9, 10, 11, 12.

---

## Quality Gates

- **Every commit:** ruff, ruff format, mypy (kernel/agents/channels/adapters/memory),
  import-linter, unit/contract/component tests (`just ci`)
- **Every phase:** merged to `main` via `--no-ff` only once independently green
  (`just ci` plus the relevant integration/e2e tier) — never accumulated on one long-lived
  branch
- **Every answer:** invariants enforced (numeric recomputation, provenance, abstain-by-default
  on empty results)

---

## Repository State

**Branch:** `main`
**Author:** hoomanesteki <esteki.net@gmail.com>

Every phase lands as its own `feat/phase-N-...` branch, fully verified, then merges to `main`
with `--no-ff` and is deleted. `main` is green after every merge, not just at the end.

---

## Getting Started (Local Development)

```bash
git clone ... && cd omniagent-ai-data-analyst
just install   # uv sync --locked --all-extras --dev
just ci        # lint + fast tests (unit, contract, component)
just test-all  # everything, including integration and e2e
```

---

**Next Action:** Phase 6 (router model, clarification `interrupt()`, real checkpointer/resume).
