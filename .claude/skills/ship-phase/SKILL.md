---
name: ship-phase
description: Land one OmniAgent 2.0 roadmap phase the way this repo actually requires - branch, real validation against live data, lint/mypy/import-linter/tests green, BUILD_STATUS.md updated honestly, correctly-authored commit, merge to main. Use when starting or finishing a phase from BUILD_STATUS.md's roadmap, or any change meant to land the same way (its own branch, merged once green).
---

# Ship an OmniAgent phase

This repo's build discipline is easy to state and easy to accidentally skip a
step of under time pressure. This skill is the checklist, not a summary of
it, follow every step in order.

## 1. Branch first

`git checkout -b feat/phase-N-short-name` off `main` before writing any code
for the phase. If code was already started on the wrong branch (including
directly on `main`), move it: do not keep building somewhere it will need to
be extracted from later.

## 2. Implement completely, not signature-first

A function or module is either a full, working implementation against the
real objects it depends on, or it does not exist yet. Never commit a body
that only raises `NotImplementedError`, returns a placeholder, or defers
logic with a `# TODO` where the spec/roadmap already says what it should do.
If a dependency this phase needs is not ready yet, work on a different,
ready phase instead of stubbing this one.

## 3. Validate against something real before calling it done

"mypy is happy and the file exists" is not done. Actually exercise the new
code:

- A new port implementation (engine, semantic provider, store) runs against
  real data, not just a fake in a unit test.
- A new graph node runs inside the real compiled graph at least once, not
  only in isolation.
- A new gate runs through the real `GuardrailPolicy` alongside the other
  seven, not alone.
- A new UI flow is driven through `streamlit.testing.v1.AppTest` or an
  actual HTTP client (`TestClient`, real `MCPServer.call_tool`), not just
  imported.

This project's history has repeatedly found real bugs this way that mypy and
unit tests alone missed, see `docs/adr/` and the build-decisions memory for
concrete examples. Treat "looks right" as a hypothesis to test, not a
conclusion.

## 4. Run the real gates locally

```
just lint       # ruff check, ruff format --check, mypy, import-linter
just test       # unit, contract, component, perf
```

Run `just test-all` instead of `just test` when the phase touches anything
integration- or e2e-shaped (a new graph wiring, a new channel, a new
adapter that other tests build fixtures around). Read the actual output;
do not trust a subagent's or your own prior turn's summary of it. Fix
failures before moving on; do not loosen a threshold or add a skip to make
a red test green unless the test itself was wrong.

## 5. Update BUILD_STATUS.md honestly

Move the phase's entry to reflect what actually shipped, in the same voice
as the existing entries (concrete file paths, what each thing does, why).
State real gaps as gaps ("Postgres conformance skipped without a live
server") rather than omitting them or implying full coverage. Do not mark a
phase's checkbox or heading `done` until this file says something a future
reader could verify against the code.

## 6. Commit correctly

- Author and committer: `hoomanesteki <esteki.net@gmail.com>`. No
  `Co-Authored-By: Claude` trailer, no other AI attribution, anywhere in the
  message.
- Conventional Commits format (`feat(scope): summary`), body explains why,
  not a restatement of the diff.
- No em dashes and no ellipses in the commit message (or in any code
  comments/docstrings this phase adds) - write plain, direct sentences
  instead.

## 7. Merge once green, then clean up

Merge the phase branch into `main` with `--no-ff` only after lint and the
relevant test tier are both green on that branch. Delete the phase branch
after merging. `main` should be green after every phase's merge, not just
once at the very end of the roadmap.
