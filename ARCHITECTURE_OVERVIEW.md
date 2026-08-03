# OmniAgent 2.0: Architecture Overview

## The Thesis

Raw text-to-SQL is 57% accurate. Add a governed semantic layer, and the same model reaches 78% accuracy (Snowflake internal testing, BIRD benchmark). OmniAgent 2.0 packages this insight as:

> **Metrics defined once → deterministic SQL → code-recomputed numbers → refusal instead of guessing → measured accuracy on every commit**

## Three-Layer Design

```
┌────────────────────────────────────────┐
│  packs/    domains + vocabulary        │
│  channels/ REST API, Streamlit, MCP    │
│  adapters/ DuckDB, Postgres, Groq      │
├────────────────────────────────────────┤
│  agents/   LangGraph nodes over Runtime│
├────────────────────────────────────────┤
│  kernel/   ports (protocols),          │
│            state, gates, envelope      │
│            NO vendor imports, ever     │
└────────────────────────────────────────┘
```

**Layering Invariant (enforced in CI):**
- Kernel imports only Python stdlib and Pydantic. No DuckDB, dbt, Groq, Streamlit.
- Adapters plug into kernel ports. Adapters know vendors; kernel doesn't.
- Agents close over a runtime object. No global state, no hardcoded paths.
- Channels call agents through REST. No capability only in the UI.

This is testable: `uv sync --extras kernel && python -c "import omniagent.kernel"` must succeed.

## The Request Lifecycle

```
Question arrives
    ↓
[fast path: verified query cache?] → re-execute → done (300ms, zero LLM calls)
    ↓ miss
[deterministic match: catalog metric?] → confident → semantic_agent (20b, 1 call)
    ↓ no match
router (20b) + sql_agent (120b, 2 candidates parallel) [4–5 calls]
    ↓
guard: recompute numerics, redact PII, verify provenance
    ↓
headline number renders (1.0s from start)
    ↓
chart (rule-based, no model)
    ↓
narration (template or 20b stream)
    ↓
critic (120b on 20% of turns, or deterministic confidence)
    ↓
answer envelope (JSON) + suggestions
    ↓
trace to Langfuse + record to ledger
    ↓
thumbs up → review queue → approved → verified query store
```

**Latency Target (p50, warm):** 1.8–2.5 seconds end-to-end.  
**Cost Target:** $0.37 per 1,000 answers (blended; was $1.94 in v1).  
**Model Calls:** 0–2 on governed, 4–5 on fallback (cap: 16 per turn).

## Core Concepts

### Ports (Protocols)

Every vendor sits behind a Protocol. The kernel only imports from `kernel/ports/`:

| Port | Implementations | Purpose |
|------|---|---|
| `EngineAdapter` | DuckDB, Postgres | Read-only SQL execution, error normalization |
| `SemanticProvider` | MetricFlow, NativeYaml | Catalog, validation, SQL compilation |
| `LLMProvider` | Groq, Ollama, OpenAI-compat | Inference and structured output |
| `VectorStore` | DuckDB VSS, LanceDB | Embedding retrieval |
| `VerifiedQueryStore` | DuckDB-backed | Approved Q/A pairs for few-shot context |
| `TimeResolver` | Gregorian, Fiscal calendars | "last quarter" → absolute dates, deterministically |

**Rule:** Every port has ≥2 in-tree implementations. A Protocol with one implementation is a rename, not an abstraction.

### SemanticQuery (Vendor-Neutral AST)

The model emits structured, vendor-neutral queries:

```python
@dataclass
class SemanticQuery:
    metrics: tuple[str, ...]           # "revenue", "net_revenue"
    group_by: tuple[str, ...] = ()     # "region", "metric_time__month"
    filters: tuple[Filter, ...] = ()   # structured: {field, op, value}
    time_range: TimeRange | None = None
    order_by: tuple[str, ...] = ()
    limit: int = 100
```

Not:
```python
# ❌ WRONG: vendor-specific Jinja
"{{ Dimension('region') }} = 'West' AND {{ Metric('revenue') }}"
```

This unlocks portability: swapping MetricFlow for Cube or Snowflake costs no changes to prompts, verified queries, or golden sets.

### Catalog Matching (Before Any Model Call)

```python
match = catalog.match("what was net revenue last quarter")
# Returns:
# MetricMatch(
#   metric="net_revenue",
#   confidence=0.95,
#   dimensions=["region", "customer_segment"],
#   ambiguous=False
# )
```

If confident and not ambiguous, route directly to `semantic_agent`. Skip the router model entirely. This single change removes one model call from ~70% of traffic.

### Recomputation Gate

Every number claimed in narration is recomputed in code:

```python
# Narrator says: "Revenue was $128,450"
claimed_value = extract_number("Revenue was $128,450")  # 128450

# Code recomputes from result set
computed_value = result_df["revenue"].sum()  # 128450

if abs(claimed_value - computed_value) > TOLERANCE:
    # ❌ Narrator hallucinated; repair by substituting correct number
    narration = narration.replace("$128,450", f"${computed_value:,.0f}")
```

This is the single strongest control against confidently wrong numbers.

### Answer Envelope (Versioned Contract)

```python
@dataclass
class AnswerEnvelope(BaseModel):
    envelope_version: str  # "1"
    kind: str              # "answer" | "abstention" | "clarification"
    headline: str | None
    narration: str | None
    values: list[MetricValue]  # each carries its DisplayFormat
    chart: ChartSpec | None
    table_ref: str | None      # handle, rows never leave storage
    executed_sql: str          # ALWAYS: provenance
    confidence: float
    assumptions: list[str]
    trace_id: str
```

This is what every channel (REST, Streamlit, MCP, email digest) consumes. No capability exists only in one channel.

### Per-Answer Invariants (Definition of Done)

Every answer must satisfy:

```python
def assert_answer_invariants(card: AnswerEnvelope):
    # Governed path always used when metric matched
    assert not (card.route == "sql_agent" and metric_match_score > 0.85)
    
    # SQL is guarded (no DROP, DML, timeouts)
    assert card.executed_sql is None or guard_passes(card.executed_sql)
    
    # Result was non-empty OR the system abstained
    assert card.row_count > 0 or card.abstained
    
    # Every stated number was recomputed and matches
    for num in extract_numbers(card.narration):
        assert num in card.computed.values()
    
    # Sensitive columns masked
    assert not contains_pii(card.narration)
    
    # Budget enforced
    assert card.llm_calls <= POLICY.max_llm_calls_per_turn
    
    # Confidence calibrated (not just claimed)
    assert 0 <= card.confidence <= 1
    
    # Provenance always present
    assert card.executed_sql is not None or card.metric_request is not None
```

This is both a contract and a CI gate. Every test, eval run, and production answer must satisfy it.

## The Five Loops

1. **Self-Correction (SQL):** error → normalized message → regenerate, max 2 retries
2. **Self-Consistency (Fallback):** 2 candidates parallel; on disagreement, 3rd from different family; take majority result set
3. **Clarification (Before Execution):** detect ambiguity at question parse time; interrupt with menu before any query
4. **Feedback (Continuous):** thumbs up → review queue → approved → verified query → retrieval corpus
5. **Eval (Every Commit):** failure → golden item → CI blocks regressions

## Testing Pyramid

| Tier | Real LLM | Real DB | Count | Blocking |
|------|----------|---------|-------|----------|
| Static | ✗ | ✗ | — | YES (ruff, mypy) |
| Unit | ✗ | ✗ | 150–250 | YES |
| Property | ✗ | ✗ | 10–20 | YES |
| Contract | ✗ | ✗ | 6 suites | YES |
| Component | ✗ | ✗ | 40–60 | YES |
| Integration | ✗ | ✓ | 25–40 | YES |
| E2E (cassettes) | ✗ | ✓ | 20–30 | YES |
| Eval (live) | ✓ | ✓ | 150+ | YES (on release) |

All LLM-touching tests are offline (mocked or cassettes). The eval tier is the only expensive tier and runs only on releases and nightly.

## Reproducibility

**All artifacts are deterministic:**

1. **Sample data:** seeded generator (`generate_samples.py --seed 1337`)
2. **Semantic models:** git-versioned dbt + MetricFlow YAML
3. **Golden sets:** YAML with absolute dates (deterministic time resolution)
4. **Compiled plans:** cached SQL, never re-run the CLI
5. **LLM calls:** cassettes for tests, Batch API for eval
6. **Clock:** frozen in tests (`time-machine`), seeded RNG

**Reproducibility check:**
```bash
git checkout build/omniagent-2.0
just install
just test                 # Must pass, same every time
make eval --subset dev    # Same EX scores every run
```

**Traced to commit:** Every answer carries trace_id. Traces are queryable in Langfuse. No two answers from different commits are confused.

## Security Model

**Read-Only Boundary:**
- DuckDB connection opened as read-only.
- Engine dialect declared (DuckDB, Postgres, etc.); adapter enforces the mode.
- Conformance test asserts that `DROP TABLE` fails at the engine level, not the prompt level.

**Parser Allow-List:**
- sqlglot parses all generated SQL before execution.
- Banned node types: Insert, Update, Delete, Drop, Alter, Create, TruncateTable, Command, Merge.
- Found at any depth of the AST → Unsafe exception → abstain.

**PII Policy (Column-Level):**
- Profiler marks sensitive columns at onboarding.
- Result previews auto-mask flagged columns.
- Full Presidio NER runs only on datasets flagged as containing free text.

**Principal & Row-Level Security:**
- `Principal(tenant_id, user_id, roles, attrs)` threaded through every call.
- Future: database role + DuckDB ATTACH via `SET SESSION` to enforce RLS.
- Every memory record scoped by `(tenant, dataset, schema_version)`.

**Gate Stack (Deterministic):**
- SQL allow-list (sqlglot)
- Row cap, statement timeout
- Empty result abstention
- Numeric recomputation
- PII column masking
- Provenance validation
- Model call budget

These run in code, not in the model.

## Cost & Performance Summary

| Configuration | Governed Latency | Fallback Latency | Cost/1000 | Quality Delta |
|---|---|---|---|---|
| v1 (baseline) | 12.6s | 6.9s | $1.94 | 0% |
| v2 (plan cache, fewer calls) | 1.8–2.5s | 3–4.5s | $0.37 | 0% (flat) |
| v2 (w/ fast path, 30% hit) | **0.3s (30%) + 2.2s (70%)** | — | **$0.28** | — |
| v2 (distilled router) | — | — | **$0.05** | measured per dataset |

The 12 optimizations (plan cache, fast path, fewer model calls, context trimming, prompt caching, etc.) are detailed in `06_PERFORMANCE_AND_COST.md`.

## Next Steps

1. **Phase 1:** Data generation + engine adapters (DuckDB, Postgres) + semantic providers (MetricFlow, NativeYaml).
2. **Phase 3:** Governed graph end-to-end (master → semantic_agent → executor).
3. **Phase 4:** Gate stack (safety first, before the fallback).
4. **Phase 9:** Eval suite (this is when you measure and publish EX on the README).

Each phase lands on the branch with Conventional Commits (author-signed). After all phases, merge to main and open for community contribution.

---

**Design Goal:** Honest portability. No "governed by configuration" claims. Build two implementations of every port. Prove it works by swapping them. That's this spec.
