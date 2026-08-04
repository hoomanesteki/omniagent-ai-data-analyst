#!/usr/bin/env python3
# ruff: noqa: T201
"""Composition root: a reproducible comparison of what happens when the
same adversarial SQL runs with no gates at all versus through the real
gate stack.

This is deliberately not a comparison against a live, ungoverned
text-to-SQL model. That would need a real LLM key and would only prove
one model's behavior on one day, which is a weaker and less reproducible
claim. The actual point of a deterministic gate stack (see
docs/adr/0005-deterministic-gate-stack.md) is that it holds regardless of
which model produced the SQL, so the fair and reproducible comparison is:
identical SQL string, gated versus not. The SQL used here is exactly
`eval/redteam.py`'s existing cases, the same ones this project's own
evaluation harness scores, not a fresh set invented for this script.

The "raw" side runs against a disposable copy of the warehouse (never the
real file) so this script is safe to re-run at will.

Usage:
    python scripts/generate_samples.py
    python scripts/load_warehouse.py
    python scripts/compare_governed_vs_raw.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import duckdb

from omniagent.adapters.engine.duckdb import DuckDBEngine
from omniagent.agents.sql_agent import make_sql_agent_node
from omniagent.eval.redteam import CASES, is_refused
from omniagent.kernel.gates import (
    GuardrailPolicy,
    empty_result_gate,
    llm_budget_gate,
    numeric_recompute_gate,
    pii_mask_gate,
    provenance_gate,
    row_cap_gate,
    sql_allowlist_gate,
    timeout_gate,
)
from omniagent.kernel.models import SqlCandidate
from omniagent.kernel.state import OmniState
from tests.fakes.llm import ScriptedLLM

_ALL_GATES = [
    sql_allowlist_gate,
    row_cap_gate,
    timeout_gate,
    empty_result_gate,
    numeric_recompute_gate,
    pii_mask_gate,
    provenance_gate,
    llm_budget_gate,
]

_SQL_AGENT_RETRIES = 2


def _raw_outcome(copy_path: Path, sql: str) -> dict[str, Any]:
    """Execute `sql` directly against a writable DuckDB connection with no
    allowlist, no row cap, no gate of any kind -- exactly what a bare
    text-to-SQL system with no safety layer would do with the same string."""
    conn = duckdb.connect(str(copy_path), read_only=False)
    try:
        conn.execute(sql)
        return {"executed": True, "error": None}
    except duckdb.Error as exc:
        return {"executed": False, "error": str(exc)}
    finally:
        conn.close()


async def _governed_outcome(engine: DuckDBEngine, case: Any) -> dict[str, Any]:
    """Run the exact same SQL through the real sql_agent gate stack,
    scripting the LLM to attempt it on every retry -- refusal here is the
    gates' doing, not the model's, since the model never stops trying."""
    llm = ScriptedLLM(
        [SqlCandidate(sql=case.induced_sql, tables_used=[])] * (_SQL_AGENT_RETRIES + 1)
    )
    node = make_sql_agent_node(
        dataset_id="ecommerce",
        engine=engine,
        llm=llm,
        model_id="compare-stand-in",
        guardrail_policy=GuardrailPolicy(gates=_ALL_GATES),
        max_retries=_SQL_AGENT_RETRIES,
    )
    state = OmniState(
        thread_id=f"compare-{case.case_id}",
        dataset_id="ecommerce",
        messages=[{"role": "user", "content": case.question}],
    )
    cmd = await node(state)
    update = cmd.update or {}
    return {"refused": is_refused(update), "error": update.get("error")}


async def run_comparison(*, warehouse_path: str | Path) -> list[dict[str, Any]]:
    engine = DuckDBEngine(warehouse_path, read_only=True)
    rows: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        for case in CASES:
            # A fresh copy per case, not one copy reused across all of them:
            # an earlier case's DROP TABLE would otherwise make a later
            # case's target table genuinely missing, which is a side effect
            # of running cases back to back, not a real finding about that
            # later case's own SQL.
            copy_path = Path(tmp_dir) / f"raw_playground_{case.case_id}.duckdb"
            shutil.copy(warehouse_path, copy_path)

            raw = _raw_outcome(copy_path, case.induced_sql)
            governed = await _governed_outcome(engine, case)
            rows.append(
                {
                    "case_id": case.case_id,
                    "category": case.category,
                    "question": case.question,
                    "induced_sql": case.induced_sql,
                    "raw_executed": raw["executed"],
                    "raw_error": raw["error"],
                    "governed_refused": governed["refused"],
                    "governed_error": governed["error"],
                }
            )
    return rows


def _print_table(rows: list[dict[str, Any]]) -> None:
    header = f"{'case':<24} {'category':<20} {'raw (no gates)':<20} {'governed':<20}"
    print(header)
    print("-" * len(header))
    for row in rows:
        raw_label = "EXECUTED" if row["raw_executed"] else "rejected by engine"
        governed_label = "refused" if row["governed_refused"] else "EXECUTED"
        print(f"{row['case_id']:<24} {row['category']:<20} {raw_label:<20} {governed_label:<20}")


def _vega_lite_spec(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = []
    for row in rows:
        values.append(
            {
                "case": row["case_id"],
                "system": "Raw (no gates)",
                "outcome": "Executed" if row["raw_executed"] else "Rejected",
            }
        )
        values.append(
            {
                "case": row["case_id"],
                "system": "Governed",
                "outcome": "Refused" if row["governed_refused"] else "Executed",
            }
        )
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": "Same adversarial SQL, gated versus not",
        "data": {"values": values},
        "mark": {"type": "bar", "cornerRadiusEnd": 4},
        "encoding": {
            "x": {"field": "case", "type": "nominal", "title": "Red team case"},
            "y": {"aggregate": "count", "type": "quantitative", "title": None},
            "column": {"field": "system", "type": "nominal", "title": None},
            "color": {
                "field": "outcome",
                "type": "nominal",
                "scale": {
                    "domain": ["Executed", "Refused", "Rejected"],
                    "range": ["#c0392b", "#1e8449", "#7f8c8d"],
                },
            },
        },
    }


_HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>Governed vs raw: same SQL, gated or not</title>
<script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
</head>
<body>
<h1>Same adversarial SQL. Gated, or not.</h1>
<p>Regenerate with <code>python scripts/compare_governed_vs_raw.py</code>.</p>
<div id="vis"></div>
<script type="text/javascript">
  vegaEmbed('#vis', {spec});
</script>
</body>
</html>
"""


def write_report(rows: list[dict[str, Any]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "governed_vs_raw.json").write_text(json.dumps(rows, indent=2))
    html_path = out_dir / "governed_vs_raw.html"
    html_path.write_text(_HTML_TEMPLATE.format(spec=json.dumps(_vega_lite_spec(rows))))
    return html_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warehouse", type=Path, default=Path("data/warehouse/omniagent.duckdb"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()

    if not args.warehouse.exists():
        raise RuntimeError(
            f"Warehouse not found at {args.warehouse}. Run scripts/generate_samples.py "
            "then scripts/load_warehouse.py first."
        )

    rows = asyncio.run(run_comparison(warehouse_path=args.warehouse))
    _print_table(rows)
    print()
    executed_raw = sum(1 for row in rows if row["raw_executed"])
    refused_governed = sum(1 for row in rows if row["governed_refused"])
    print(
        f"Raw (no gates): {executed_raw}/{len(rows)} adversarial queries executed. "
        f"Governed: {refused_governed}/{len(rows)} refused."
    )
    html_path = write_report(rows, args.out_dir)
    print(f"Chart written to {html_path}")


if __name__ == "__main__":
    main()
