"""Conformance tests for the DuckDB EngineAdapter against the kernel port."""

import pytest

from omniagent.kernel.ports.engine import EngineError, ReadOnlyMode


@pytest.mark.contract
class TestDuckDBEngineConformance:
    def test_capabilities_report_native_readonly(self, ecommerce_warehouse):
        caps = ecommerce_warehouse.capabilities()
        assert caps.dialect == "duckdb"
        assert caps.readonly == ReadOnlyMode.NATIVE
        assert caps.supports_cancel is True

    def test_execute_returns_expected_row(self, ecommerce_warehouse):
        result = ecommerce_warehouse.execute(
            "SELECT COUNT(*) AS n FROM ecommerce_orders", row_cap=100
        )
        assert result.columns == ("n",)
        assert result.batches == [(4,)]
        assert result.row_count == 1
        assert result.truncated is False
        assert result.elapsed_ms >= 0

    def test_execute_respects_row_cap_and_reports_truncation(self, ecommerce_warehouse):
        result = ecommerce_warehouse.execute(
            "SELECT * FROM ecommerce_orders ORDER BY order_id", row_cap=2
        )
        assert result.row_count == 2
        assert result.truncated is True

    def test_execute_no_truncation_when_under_cap(self, ecommerce_warehouse):
        result = ecommerce_warehouse.execute(
            "SELECT * FROM ecommerce_orders ORDER BY order_id", row_cap=100
        )
        assert result.row_count == 4
        assert result.truncated is False

    def test_execute_binds_params_not_interpolated(self, ecommerce_warehouse):
        """A filter value must arrive as a bound parameter, never string-built into the SQL."""
        result = ecommerce_warehouse.execute(
            "SELECT order_id FROM ecommerce_orders WHERE order_status = ?",
            params=["completed"],
            row_cap=100,
        )
        assert {row[0] for row in result.batches} == {"O1", "O2", "O4"}

    def test_execute_rejects_write_even_if_parsed(self, ecommerce_warehouse):
        """The read-only connection is the wall, independent of any SQL-text gate."""
        with pytest.raises(EngineError) as exc_info:
            ecommerce_warehouse.execute("DELETE FROM ecommerce_orders", row_cap=10)
        assert exc_info.value.code in ("READ_ONLY_VIOLATION", "ENGINE_ERROR")

    def test_schema_snapshot_lists_tables_and_columns(self, ecommerce_warehouse):
        snapshot = ecommerce_warehouse.schema_snapshot("ecommerce")
        assert "ecommerce_orders" in snapshot["tables"]
        columns = {c["name"] for c in snapshot["tables"]["ecommerce_orders"]}
        assert {"order_id", "customer_id", "order_status", "order_total"} <= columns

    def test_schema_snapshot_scoped_to_dataset_prefix_only(self, ecommerce_warehouse):
        """Tables are disambiguated by a `{dataset_id}_` name prefix, not a DuckDB
        schema (see scripts/load_warehouse.py: every pack's tables share one flat
        warehouse) -- an unrelated or non-prefix-matching dataset_id sees nothing."""
        snapshot = ecommerce_warehouse.schema_snapshot("saas")
        assert snapshot["tables"] == {}

    def test_normalize_error_missing_table(self, ecommerce_warehouse):
        with pytest.raises(EngineError) as exc_info:
            ecommerce_warehouse.execute("SELECT * FROM nonexistent_table", row_cap=10)
        assert exc_info.value.code == "MISSING_TABLE"

    def test_normalize_error_missing_column(self, ecommerce_warehouse):
        with pytest.raises(EngineError) as exc_info:
            ecommerce_warehouse.execute(
                "SELECT nonexistent_column FROM ecommerce_orders", row_cap=10
            )
        assert exc_info.value.code in ("MISSING_COLUMN", "BINDER_ERROR")

    def test_normalize_error_syntax_error(self, ecommerce_warehouse):
        with pytest.raises(EngineError) as exc_info:
            ecommerce_warehouse.execute("SELEKT * FROM ecommerce_orders", row_cap=10)
        assert exc_info.value.code == "SYNTAX_ERROR"
