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

### Phase 6: Routing & Durability ✅

- `agents/router.py`: one narrow LLM call behind master's deterministic catalog miss,
  deciding a genuine out-of-scope data question (routed to the guarded SQL fallback) from
  a non-data intent or a question that needs clarification first. Governed (catalog-matched)
  questions never reach it at all.
- `agents/clarify.py`: pauses graph execution via LangGraph's `interrupt()` instead of
  ending the turn; a caller resumes with `Command(resume=answer)`, re-entering the same
  deterministic dispatch (`dispatch_match`, extracted from `master_node` so both share it)
  an original question would have gone through, including looping back through `clarify`
  again on a still-ambiguous answer.
- A real `SqliteSaver` checkpointer wired into the composition root: `/resume` in the
  FastAPI service answers a pending interrupt; `/ask` continues an existing thread through
  the same checkpointer-backed accumulation, which is also what a genuine follow-up
  question uses now instead of `/resume`. `AnswerEnvelope.resumable` tells a client which
  of those two a `kind="clarification"` response actually is.
- `/feedback` now creates a verified query on a thumbs-up for a fallback-sourced answer,
  closing the gap Phase 5 had left as an "honest audit-log sink."
- Fixed a latent bug this phase's checkpointer exercised for the first time: `assumptions`
  and `sql_candidates` used an `add` reducer meant for within-turn accumulation, which then
  kept concatenating a prior turn's values onto every later turn's once state genuinely
  persisted across separate `/ask` calls on the same thread.

---

### Phase 9: Evaluation ✅

- `omniagent/eval/goldgen.py`: backwards generation. For every metric the catalog knows
  (and one valid breakdown dimension per metric), compiles and executes the real query
  against the real warehouse for ground truth, then attaches several template phrasings.
  Nothing checked in as static data; regenerated fresh from the pack YAML and warehouse
  every run, so it can never drift out of sync with either.
- `omniagent/eval/scorers.py`: execution accuracy (row-order-independent, float-tolerant),
  a generic categorical accuracy (route/metric-match), schema-link recall, and a percentile
  bootstrap confidence interval with a fixed default seed.
- `omniagent/eval/redteam.py`: deterministic destructive/exfiltration cases, each scripting
  the LLM to attempt its induced SQL on every retry attempt, proving refusal is the gate
  stack's doing, not the model's.
- `scripts/run_eval.py` (composition root, same placement reasoning as `scripts/serve.py`) +
  `just eval`. Run against the real warehouse: 147 golden items across both packs, 6 red
  team cases, 100% on execution/route/metric-match accuracy and red team refusal.
- Found and fixed two real bugs this exercised for the first time: `execution_accuracy`
  crashing comparing `None` to a float when sorting rows for comparison, and a join-path
  bug in `native_yaml.py` where a two-hop join spliced in an unrelated model's join type
  and condition instead of the one that actually applied to that edge (`compile()` never
  runs its own SQL, so this only surfaced at real execution). Added a `saas_warehouse` test
  fixture, since no test had exercised real joins across the SaaS pack's five models before.

CI workflow wiring landed with Phase 10 below (`.github/workflows/eval.yml` runs the harness
nightly); paired comparison (McNemar) gating on regressions was not built.

---

### Phase 10: MLOps and Observability ✅

- `kernel/telemetry.py`: a `Tracer` recording one masked-input span per node, wired into
  `build_governed_graph` via a `_traced` wrapper (no node's own code changes). A
  `GraphInterrupt`-based pause records as paused, not errored, since `agents/clarify.py`
  pausing mid-turn is a deliberate, successful control-flow event, not a failure.
- `kernel/ports/ledger.py` + `adapters/ledger/duckdb_ledger.py`: a durable, queryable audit
  table recording each turn's masked question, route, matched metric, executed SQL,
  confidence, and error. Wired into `channels/service.py`'s `/ask` and `/resume`, and into
  `scripts/serve.py`'s composition root. The same `tracers` dict passed to
  `build_governed_graph` is also handed to the service layer so it can pop a completed
  turn's entry (no unbounded memory growth) while a paused turn's tracer survives until
  `/resume` actually finishes it.
- `tests/perf/`: hermetic behavior tests. Call-count spies, subprocess spies, and CPU-time
  (not wall-clock, to survive `-n auto` contention) budgets. Found a real bug:
  `Catalog._contains_phrase` recompiled a fresh regex on every call, ~20x slower than
  necessary once a catalog reaches a few hundred metrics. Fixed with an `lru_cache` on the
  compiled pattern.
- `.github/workflows/{ci,eval,release}.yml`: validated with `yamllint` (a real dev
  dependency now, tested against the checked-in `.yamllint` config) and `actionlint`
  (installed locally for this pass, not wired into the test suite itself since it's a Go
  binary this repo can't assume is present everywhere). `ci.yml` runs lint plus every test
  tier on push/PR; `eval.yml` runs the harness nightly and on demand; `release.yml` validates
  a pushed tag against `pyproject.toml`'s own version before creating a GitHub Release.

**Honestly still open (not blocking, but real gaps):** a continuous-tuning pipeline and a
nightly perf-vs-baseline comparison were not built — `eval.yml`'s nightly run reports the
current scorecard but does not yet store or diff against a historical baseline.

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

**Critical Path:** 0 → 1 → 3 → 4 → 5 → 6 → 7 → 8 → 9 (5 landed ahead of 6, since 6's router
depends on 5's fallback already existing to route into; this did not change 6's own scope)

**Minimum MVP (complete):** Phases 0, 1, 3, 4, 7, 8 on e-commerce and SaaS.

**Also complete beyond MVP:** Phase 2 (real LLM adapters), Phase 5 (guarded fallback),
Phase 6 (routing and durability), Phase 9 (evaluation harness), Phase 10 (MLOps/observability).

**Still open:** dbt/MetricFlow as the semantic layer's second provider (NativeYAML is the
fully-exercised primary); Postgres engine conformance (written, skipped without a live server);
a continuous-tuning pipeline and nightly perf-vs-baseline comparison (see Phase 10's honest
gaps above); Phases 11, 12.

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

**Next Action:** Phase 11 (MCP server, Docker packaging, architecture decision records).
