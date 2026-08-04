"""Integration tests for scripts/compare_governed_vs_raw.py: the same red
team SQL run raw (no gates, against a disposable warehouse copy) and
governed (through the real gate stack), proving the comparison script
itself reports real, reproducible outcomes rather than asserting anything
about which specific cases the raw side happens to execute (that depends
on DuckDB's own SQL dialect quirks, which are not this project's to
guarantee)."""

import json

import duckdb
import pytest

from omniagent.eval.redteam import CASES
from scripts.compare_governed_vs_raw import _raw_outcome, run_comparison, write_report


@pytest.mark.integration
class TestRawOutcome:
    def test_a_destructive_statement_with_no_gates_actually_executes(self, tmp_path):
        db_path = tmp_path / "playground.duckdb"
        conn = duckdb.connect(str(db_path))
        conn.execute("CREATE TABLE victims (id INTEGER)")
        conn.execute("INSERT INTO victims VALUES (1), (2)")
        conn.close()

        result = _raw_outcome(db_path, "DROP TABLE victims")

        assert result["executed"] is True
        assert result["error"] is None
        conn = duckdb.connect(str(db_path))
        tables = conn.execute("SHOW TABLES").fetchall()
        conn.close()
        assert tables == []

    def test_invalid_sql_reports_the_real_engine_error_not_a_fabricated_one(self, tmp_path):
        db_path = tmp_path / "playground.duckdb"
        duckdb.connect(str(db_path)).close()

        result = _raw_outcome(db_path, "DROP TABLE this_table_does_not_exist")

        assert result["executed"] is False
        assert "does not exist" in result["error"].lower()


@pytest.mark.integration
class TestRunComparison:
    async def test_every_red_team_case_is_refused_by_the_governed_side(self, ecommerce_warehouse):
        # ecommerce_warehouse is a tmp_path-backed DuckDB file, same shape
        # run_comparison expects; it is never mutated since the raw side
        # only ever touches its own throwaway copy.
        rows = await run_comparison(warehouse_path=ecommerce_warehouse.database_path)

        assert len(rows) == len(CASES)
        assert all(row["governed_refused"] for row in rows)

    async def test_raw_side_actually_executes_at_least_one_destructive_case(
        self, ecommerce_warehouse
    ):
        """Not every case: DuckDB's own dialect happens to reject a couple
        of these (e.g. legacy SELECT INTO syntax) for reasons that have
        nothing to do with safety. At least the plain DROP TABLE case,
        which is valid anywhere, must genuinely execute with no gates."""
        rows = await run_comparison(warehouse_path=ecommerce_warehouse.database_path)

        by_case = {row["case_id"]: row for row in rows}
        assert by_case["drop-table-direct"]["raw_executed"] is True

    async def test_original_warehouse_file_is_never_mutated(self, ecommerce_warehouse):
        db_path = ecommerce_warehouse.database_path
        before = duckdb.connect(str(db_path), read_only=True).execute("SHOW TABLES").fetchall()

        await run_comparison(warehouse_path=db_path)

        after = duckdb.connect(str(db_path), read_only=True).execute("SHOW TABLES").fetchall()
        assert before == after


@pytest.mark.integration
class TestWriteReport:
    async def test_writes_a_json_file_and_a_self_contained_html_chart(
        self, ecommerce_warehouse, tmp_path
    ):
        rows = await run_comparison(warehouse_path=ecommerce_warehouse.database_path)
        out_dir = tmp_path / "reports"

        html_path = write_report(rows, out_dir)

        assert html_path.exists()
        assert "vegaEmbed" in html_path.read_text()
        json_rows = json.loads((out_dir / "governed_vs_raw.json").read_text())
        assert len(json_rows) == len(CASES)
