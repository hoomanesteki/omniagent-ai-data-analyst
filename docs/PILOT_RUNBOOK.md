# Pilot Runbook

A practical guide for running a pilot with a prospective customer: what to
prepare, what to show, what to ask, and how to judge whether it worked.

## Before the call

1. Clone the repo and run `just install`.
2. `python scripts/generate_samples.py && python scripts/load_warehouse.py`
   to build the local warehouse. This takes under a minute.
3. Run `just eval` once and read the scorecard. If a number is below 100%,
   know why before the call, not during it.
4. Run `just demo` once end to end so the first run's cold-start output
   (model downloads, warehouse loading) doesn't happen live.
5. Have `docker compose up --build` ready as a fallback if the local
   Python environment has any issue on the customer's machine — the whole
   stack should be reachable at `localhost:8000` (API) and `localhost:8501`
   (UI) within about 15 seconds of that command finishing.
6. Decide which pack to lead with. E-commerce reads as retail/DTC; SaaS
   reads as B2B subscription. Pick whichever matches the prospect's own
   business, since the metrics landing as recognizable is most of the
   demo's persuasive power.

## The 90 seconds (`python scripts/demo.py`)

Run it once, narrate as it prints. It genuinely executes every act; there
is nothing to fake or skip if a step is slow.

1. **The trap** (~15s): the exact SQL a prompt injection or a bare
   text-to-SQL system would run, executed with no gates on a disposable
   copy of the data, then refused by the real gate stack. This is the
   single most important thing to land: the refusal is not the model
   being polite, it is a deterministic check that holds regardless of
   which model produced the SQL.
2. **The answer card** (~15s): a real breakdown question, real SQL, real
   numbers, a chart. Point at the `executed_sql` field — nothing here is
   narrated without being computed first.
3. **The clarification** (~20s): a genuinely ambiguous question pauses and
   asks back instead of guessing, then resumes exactly where it paused
   once answered. This is the moment to say "this is what 'abstain by
   default' looks like from the outside."
4. **The MCP reveal** (~20s): the identical governed graph, answering
   through MCP instead of a human. If the prospect uses any agent tooling
   internally (Claude, an internal copilot, anything that speaks MCP),
   this is where that conversation starts.
5. **The scorecard** (~20s): real accuracy numbers, generated fresh from
   real execution against real data, with a bootstrap confidence interval,
   not a hand-picked demo result.

## Questions worth asking the prospect live

- "What's a question your analysts get asked weekly that takes them an
  hour to answer?" — try to answer it live using their actual metric
  names once the semantic layer is pointed at a pack resembling their data.
- "What's the question you'd never trust an AI to answer unsupervised?" —
  this is the question to run through `scripts/compare_governed_vs_raw.py`'s
  logic live if they're willing: show what happens with no gates, then
  with the real gate stack.
- "Where does your data actually live?" — this determines how much of the
  onboarding story (a new pack's YAML, a new engine adapter) is relevant
  versus how much is already covered by DuckDB + NativeYAML.

## Reading the scorecard with them

- `execution_accuracy`, `route_accuracy`, `metric_match_accuracy` are all
  100% on the shipped golden sets because those sets are generated from
  the same catalog and warehouse the graph runs against (see
  [docs/adr/0011](adr/0011-backwards-generated-golden-set.md)) — this is
  the ceiling for a well-modeled domain, not a claim about performance on
  a pack that does not exist yet. Be direct about this distinction:
  the number proves the pipeline is correct for what it has been taught,
  not that it can answer anything.
- `redteam_refusal_rate` is the number that matters most for a security or
  compliance stakeholder in the room. It is not a sampled estimate: every
  case is scripted to keep attacking on every retry, so 100% means the
  gates held against a model that never stopped trying, not one that
  behaved politely on the first attempt.
- Point at the confidence interval columns. A pilot with a much smaller
  golden set than the shipped 147 items will have wider intervals; that is
  the harness being honest about sample size, not a defect.

## If something breaks live

- `/ask` returns an error mentioning `GROQ_API_KEY`: the demo can still
  run in full via `scripts/demo.py` and `scripts/run_eval.py`, both of
  which use a deterministic stand-in when no key is set and are exact for
  the questions they ask (see `_RepeatingExtractionLLM`'s docstring in
  `scripts/run_eval.py`). Say so plainly rather than scrambling for a key.
- A gate refuses something you expected to succeed: this is very likely
  correct behavior, not a bug — check `docs/adr/0005` for what each gate
  actually checks before assuming otherwise.
- Docker's `init` service fails: it only ever generates sample data and
  loads a warehouse; rerun `docker compose up --build` after
  `docker compose down --volumes`, which clears the named volume it wrote to.

## What a successful pilot looks like

- The prospect can name a real question from their own business that the
  semantic layer, once pointed at their schema, would answer deterministically.
- The prospect understands the difference between "the model refused"
  and "a gate refused," and cares about that difference.
- There is a concrete next step: a real pack for their data, a real engine
  connection, or a scoped trial period with their own analysts asking
  real questions against it.

## After the call

Update `BUILD_STATUS.md`-style honesty applies here too: write down what
actually happened, including anything that did not work, before it is
forgotten. A pilot that surfaces a real gap is more valuable than one that
looked perfect and taught nothing.
