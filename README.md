# OmniAgent

A governed answer engine for tabular data. Ask a question in plain English,
get back a number with the SQL that produced it, or a clear refusal instead
of a confident guess. Semantic layer first, guarded SQL fallback second,
a deterministic gate stack around both.

## The scorecard

Regenerated fresh from real data on every run, never hand-assembled:

```bash
python scripts/generate_samples.py
python scripts/load_warehouse.py
python scripts/run_eval.py
```

```text
metric                           n     mean   ci_low  ci_high
-------------------------------------------------------------
execution_accuracy             147   100.0%   100.0%   100.0%
route_accuracy                 147   100.0%   100.0%   100.0%
metric_match_accuracy          147   100.0%   100.0%   100.0%
redteam_refusal_rate             6   100.0%   100.0%   100.0%
```

147 golden questions across two packs (e-commerce, SaaS), generated
backwards from real execution against the real warehouse, not hand-written
(see [docs/adr/0011](docs/adr/0011-backwards-generated-golden-set.md)). 6
red team cases (prompt injection, destructive SQL, PII exfiltration), each
scripted to keep trying its attack on every retry, refused every time by
the gate stack, not by a model declining.

## The same SQL, gated or not

```bash
python scripts/compare_governed_vs_raw.py
```

Runs the red team's own SQL strings two ways: once with no gates at all
against a disposable copy of the warehouse, once through the real gate
stack. As of this writing: **4 of 6 execute with no gates**, all 6 are
refused when governed. The two that fail unguarded do so by DuckDB dialect
luck (legacy syntax the parser happens to reject), not by design, which is
the actual point: a deterministic gate stack holds regardless of the SQL
dialect, the model, or the day. Chart written to `reports/governed_vs_raw.html`.

## 90 seconds, end to end

```bash
python scripts/demo.py
```

Five acts, all real code, no GROQ_API_KEY required: the trap above, an
answer card with a chart, a genuinely ambiguous question that pauses for
clarification and resumes, the same governed graph answering through MCP
instead of a human, then the scorecard.

## How it decides

```text
question
   │
   ▼
deterministic catalog match ──miss──▶ router (1 LLM call) ──▶ clarify or fallback
   │ hit                                                            │
   ▼                                                                ▼
semantic_agent (1 LLM call:                                  sql_agent (schema-linked
 time phrase + filters)                                       generation, bounded retry)
   │                                                                │
   ▼                                                                ▼
compile deterministic SQL                                    generated SQL
   │                                                                │
   └──────────────────────────┬─────────────────────────────────────┘
                               ▼
                    8-gate GuardrailPolicy (pre- and post-execution)
                               │
                               ▼
                    execute, narrate, chart, suggest follow-ups
```

A model is never asked "what should happen next in the graph." It answers
narrow, typed questions (does this phrase name a known metric filter, is
this SQL worth attempting) whose outputs feed a graph edge a human already
designed. See [docs/adr/0002](docs/adr/0002-gated-autonomy-deterministic-routing.md).

## Try it

```bash
git clone <this repo> && cd omniagent-ai-data-analyst
just install                    # uv sync --locked --all-extras --dev
python scripts/generate_samples.py
python scripts/load_warehouse.py
just eval                       # the scorecard above
just compare                    # the governed-vs-raw chart
just demo                       # the 90-second walkthrough

export GROQ_API_KEY=...         # a real model, for the actual services
just serve                      # REST API on :8000
just serve-mcp                  # MCP server, stdio by default

docker compose up --build       # the whole stack (init, api, ui): see below
```

`docker compose up` builds one image, generates both packs' sample data
and loads the warehouse in an `init` service, then brings up the REST API
(`:8000`) and Streamlit UI (`:8501`); an `mcp` service is available behind
`docker compose --profile mcp up`. Needs `GROQ_API_KEY` in the environment
(or a `.env` file) to actually answer questions; without one it still
builds, generates data, and serves `/health`/`/datasets`, failing fast
with a clear error on `/ask` instead of guessing.

## What's actually here

- **Semantic layer first** ([docs/adr/0001](docs/adr/0001-semantic-layer-first-guarded-fallback.md)):
  a catalog match compiles to deterministic SQL with one narrow LLM call
  for filter/time extraction. No catalog match escalates to a guarded SQL
  fallback with schema linking and a bounded self-correction loop, behind
  the same gate stack.
- **A deterministic gate stack, not an ML guardrail** ([0005](docs/adr/0005-deterministic-gate-stack.md)):
  SQL allowlist, row cap, timeout, empty-result abstention, numeric
  recompute against ground truth, PII masking, provenance, LLM budget.
  Every gate runs, not just the first that fails, for a full audit trail.
- **Durable, resumable clarification** ([0007](docs/adr/0007-interrupt-based-clarification.md)):
  a genuinely ambiguous question pauses the graph via LangGraph's
  `interrupt()` and resumes exactly where it left off once answered.
- **An evaluation harness with published numbers** ([0011](docs/adr/0011-backwards-generated-golden-set.md)):
  golden sets generated backwards from real execution, never checked in as
  static data, so they can't drift out of sync with the packs or warehouse.
- **MCP with no raw-SQL tool** ([0012](docs/adr/0012-mcp-mirrors-rest-no-raw-sql.md)):
  the same four capabilities (discover, ask, resume, feedback) the REST API
  and the Streamlit UI get, nothing more direct, over the same gate stack.
- **Two real datasets, one real engine, one real semantic provider**:
  e-commerce and SaaS packs, fully exercised through DuckDB and a
  self-contained YAML semantic layer. Postgres and dbt/MetricFlow are
  written to their full ports but honestly documented as open, not faked
  (see [BUILD_STATUS.md](BUILD_STATUS.md)).

Full phase-by-phase status, what's genuinely done versus honestly open, and
every real bug this build's own validate-then-fix discipline caught: see
[BUILD_STATUS.md](BUILD_STATUS.md). Architecture decisions, one per real
design choice made across the build: [docs/adr/](docs/adr/). Running a
pilot: [docs/PILOT_RUNBOOK.md](docs/PILOT_RUNBOOK.md).

## License

MIT. See [LICENSE](LICENSE).
