# OmniAgent 2.0 Build Status

## Completed Phases

### Phase 0: Scaffold ✅ (commit 970bdce)

- ✅ Kernel port Protocols (engine, semantic, LLM, stores, identity, time, grounding)
- ✅ Layering enforcement via import-linter
- ✅ pyproject.toml with optional extras
- ✅ pytest configuration with test pyramid markers
- ✅ .pre-commit-config.yaml (ruff, mypy, gitleaks)
- ✅ CONTRIBUTING.md with Conventional Commits guide
- ✅ justfile for common tasks

**Branch:** `build/omniagent-2.0`  
**Commits:** 1 (author: hoomanesteki)

---

## Next Phases (In Order)

### Phase 1: Data, Engine, and Semantic Layer (2–3 days)

**Goal:** Two datasets modeled with working metrics; second engine proves the port.

**Deliverables:**
- `scripts/generate_samples.py` for e-commerce and SaaS datasets
- E-commerce pack: dbt project, staging/mart models, semantic YAML
- SaaS pack including cohort marts
- `adapters/engine/duckdb.py` (EngineAdapter impl)
- `adapters/engine/postgres.py` (second engine, proves port)
- `adapters/semantic/metricflow.py` (in-process, no CLI)
- `adapters/semantic/native_yaml.py` (second semantic provider)
- Catalog with synonym and embedding-based matching
- TimeResolver with CalendarSpec
- Engine and semantic conformance suites

**Done When:**
- Both packs build with `dbt build` and `mf validate-configs`
- `SemanticQuery` for net revenue by month compiles in < 300 ms (no subprocesses)
- Conformance suites pass for both engines
- TimeResolver returns correct ranges across Gregorian and July fiscal calendars

---

### Phase 2: Model Provider and Typed Contracts (0.5 days)

**Deliverables:**
- `adapters/llm/groq.py` (Groq LLMProvider)
- `adapters/llm/ollama.py` (second LLM impl, proves port)
- Role registry from config/models.yaml
- All Pydantic contracts (Route, SqlCandidate, ChartSpec, etc.)

**Done When:**
- Structured output returns valid Route
- Provider conformance passes against cassettes (no API key)
- Swapping role registry to Ollama runs same test successfully

---

### Phase 3: Governed Path End-to-End (2 days)

**Deliverables:**
- `agents/master.py` (deterministic matching first, router on miss)
- `agents/semantic_agent.py` (catalog validation, tier escalation)
- `agents/executor.py` (guarded execution)
- Graph wiring and state machine

**Done When:**
- "What was net revenue last quarter?" on e-commerce returns correct number
- Response includes compiled SQL
- Exactly one model call (verified by call spy)
- Warm p50 latency < 1.5 seconds

---

### Phase 4: Gate Stack (1–2 days)

**Deliverables:**
- SQL allow-list via sqlglot
- Row cap, timeout, empty result, numeric recompute
- PII column policy
- Provenance capture
- Answer ledger schema
- Composable GuardrailPolicy with pack overlays

**Done When:**
- DROP, stacked statements, and DML-in-CTE all raise Unsafe
- Empty results abstain (no number in response)
- Corrupted narration is caught and repaired by recomputation
- Flagged columns are masked
- Every answer carries SQL, row count, assumptions

---

### Phase 5: Guarded Fallback (2 days)

**Deliverables:**
- Vector store adapter (DuckDB VSS)
- Schema indexing at pack install
- SQL agent with schema linking
- Retrieval of verified queries
- Self-correction loop (max 2 retries)
- Fast path via verified query cache
- Value dictionary for entity binding

**Done When:**
- Out-of-scope questions produce valid SELECT statements
- Broken queries self-correct within budget or abstain
- Thumbs up creates verified query; same question hits fast path in < 500 ms
- Schema version invalidates stored queries

---

### Phase 6: Routing & Durability (1 day)

**Deliverables:**
- Router model behind deterministic match
- Clarification node with interrupt()
- Checkpointer (SQLite local, Postgres for scale)
- Resume via Command(resume=...)

**Done When:**
- Governed questions never touch SQL agent (trajectory assertion)
- Ambiguous questions clarify before execution
- Follow-ups use checkpointed context

---

### Phase 7: Narration & Streaming (1–2 days)

**Deliverables:**
- Template-first narrator (zero calls for single KPI)
- Deterministic chart heuristic (Vega Lite)
- Conditional critic (after draft, ~20% of turns)
- Determininistic confidence
- Asynchronous suggester

**Done When:**
- Single KPI answers use zero narration model calls
- Chart types match rule table
- Critic skipped on validated governed answers
- TTFN < 1.2 seconds
- Narration contains no absent numbers

---

### Phase 8: Interface (2 days)

**Deliverables:**
- Streamlit app consuming only REST API
- Answer card UI
- Onboarding wizard (native YAML target)
- REST service (`/ask`, `/resume`, `/datasets`, `/feedback`)
- Option for CLI

**Done When:**
- User can pick dataset, see starters, ask question, get answer card
- Thumbs up enters review queue
- Interface has no capability the API lacks

---

### Phase 9: Evaluation (2–3 days)

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

### Phase 10: MLOps and Observability (1–2 days)

**Deliverables:**
- Langfuse spans on every node (inputs masked)
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

### Phase 11: MCP and Packaging (1–2 days)

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

### Phase 12: Demo and Pilot Kit (1 day)

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

**Total Estimate:** 12–15 focused engineer days (compared to v1's 20–30)

**Key Differences from v1:**
1. No forecasting agent (cut from Phase 0)
2. No voice input
3. No clinic dataset in v1 (deferred to local-model release)
4. Guardrail models are supplement, not boundary
5. Chart selection is rule-based, not LLM
6. Deterministic confidence model (not claimed)
7. Second implementation of every port built in Phase 1

**Critical Path:** 0 → 1 → 3 → 4 → 5 → 6 → 7 → 8 → 9

**Parallel Streams:** 10 overlaps 5–8; 2 can start after 1.

**Minimum MVP:** Phases 0, 1, 3, 4, 7, 8 on e-commerce only (1 week). Add Phase 9 before any external demo.

---

## Quality Gates

- **Every commit:** ruff, mypy, import-linter, unit/property/contract/component tests
- **Every PR to main:** full evaluation (golden sets) or nightly
- **Every release:** red team 100% pass rate, SLO gates on latency/cost/accuracy
- **Every answer:** invariants enforced (numeric recomputation, provenance, confidently-wrong = 0)

---

## Repository State

**Branch:** `build/omniagent-2.0`  
**Latest:** `970bdce` (Phase 0 complete)  
**Author:** hoomanesteki <esteki.net@gmail.com>

All commits carry conventional message format. Merge to main only after PR review and all CI gates pass.

---

## Getting Started (Local Development)

```bash
# Clone and switch to build branch
git clone ... && cd omniagent-ai-data-analyst
git checkout build/omniagent-2.0

# Set up environment (Python 3.12 via uv)
just install

# Run fast tests and lint
just ci

# Next phase: Phase 1 (data + engines)
# See 13_ROADMAP.md in the spec for detailed acceptance criteria
```

---

**Next Action:** Implement Phase 1 (data generation, DuckDB engine, MetricFlow semantic provider).
