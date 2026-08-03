"""Unit tests for the provenance gate with parametrized test cases."""

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from omniagent.kernel.gates.exceptions import Unsafe
from omniagent.kernel.gates.provenance import (
    _add_provenance_annotation,
    _extract_filters_from_sql,
    _extract_table_info_from_sql,
    _is_numeric,
    provenance_gate,
)
from omniagent.kernel.state import OmniState


# Helper to run async tests
def async_test(coro):
    """Run async test function."""

    def wrapper(*args, **kwargs):
        return asyncio.run(coro(*args, **kwargs))

    return wrapper


# =============================================================================
# Tests for _is_numeric helper
# =============================================================================


class TestIsNumeric:
    """Test numeric type detection."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            # Happy path: numeric values
            (42, True),
            (3.14, True),
            (Decimal("99.99"), True),
            ("123", True),
            ("45.67", True),
            ("-100", True),
            ("1e10", True),
            ("NaN", True),  # float("NaN") succeeds
            ("inf", True),  # float("inf") succeeds
            # Edge cases and violations
            (None, False),
            ("", False),
            ("abc", False),
            ("123abc", False),
            ([], False),
            ({}, False),
        ],
        ids=[
            "int_value",
            "float_value",
            "decimal_value",
            "string_int",
            "string_float",
            "string_negative",
            "scientific_notation",
            "nan_string",
            "inf_string",
            "none_value",
            "empty_string",
            "text_string",
            "mixed_text_number",
            "empty_list",
            "empty_dict",
        ],
    )
    def test_is_numeric(self, value: Any, expected: bool) -> None:
        """Test _is_numeric with various value types."""
        result = _is_numeric(value)
        assert result == expected


# =============================================================================
# Tests for _extract_table_info_from_sql helper
# =============================================================================


class TestExtractTableInfoFromSQL:
    """Test SQL table and column extraction."""

    @pytest.mark.parametrize(
        "sql,expected_tables_keys",
        [
            # Happy path: simple SELECT queries
            ("SELECT * FROM users", {"users"}),
            ("SELECT id, name FROM customers", {"customers"}),
            (
                "SELECT a.id, a.name FROM accounts a",
                {"accounts"},
            ),
            # Multiple tables (JOIN)
            (
                "SELECT u.id, o.total FROM users u JOIN orders o ON u.id = o.user_id",
                {"users", "orders"},
            ),
            # Multiple JOINs
            (
                "SELECT * FROM t1 JOIN t2 ON t1.id = t2.t1_id JOIN t3 ON t2.id = t3.t2_id",
                {"t1", "t2", "t3"},
            ),
            # Edge cases: None and empty strings
            (None, set()),
            ("", set()),
            # Quoted table names
            (
                'SELECT * FROM "users"',
                {"users"},
            ),
        ],
        ids=[
            "simple_from",
            "select_columns",
            "aliased_table",
            "single_join",
            "multiple_joins",
            "none_sql",
            "empty_sql",
            "quoted_table",
        ],
    )
    def test_extract_table_info_happy_path(self, sql: Any, expected_tables_keys: set[str]) -> None:
        """Test successful table extraction."""
        result = _extract_table_info_from_sql(sql)
        assert set(result.keys()) == expected_tables_keys
        # Verify each table has a list (may be empty or contain columns)
        for cols in result.values():
            assert isinstance(cols, list)

    @pytest.mark.parametrize(
        "sql,forbidden_op",
        [
            ("DROP TABLE users", "DROP"),
            ("DELETE FROM users WHERE id = 1", "DELETE"),
            ("INSERT INTO users VALUES (1, 'John')", "INSERT"),
            ("UPDATE users SET name = 'Jane'", "UPDATE"),
            ("ALTER TABLE users ADD COLUMN age INT", "ALTER"),
            ("CREATE TABLE new_table (id INT)", "CREATE"),
            ("TRUNCATE TABLE users", "TRUNCATE"),
            ("MERGE INTO users", "MERGE"),
            # Case insensitivity
            ("drop table users", "DROP"),
            ("delete from users", "DELETE"),
            ("insert into users", "INSERT"),
            ("update users set x=1", "UPDATE"),
            ("alter table users", "ALTER"),
            ("create table t", "CREATE"),
        ],
        ids=[
            "drop_table",
            "delete_from",
            "insert_into",
            "update_set",
            "alter_table",
            "create_table",
            "truncate_table",
            "merge_into",
            "drop_lowercase",
            "delete_lowercase",
            "insert_lowercase",
            "update_lowercase",
            "alter_lowercase",
            "create_lowercase",
        ],
    )
    def test_extract_table_info_forbidden_operations(self, sql: str, forbidden_op: str) -> None:
        """Test that forbidden operations raise Unsafe."""
        with pytest.raises(Unsafe) as exc_info:
            _extract_table_info_from_sql(sql)
        assert "forbidden operation" in str(exc_info.value.reason).lower()


# =============================================================================
# Tests for _extract_filters_from_sql helper
# =============================================================================


class TestExtractFiltersFromSQL:
    """Test WHERE clause filter extraction."""

    @pytest.mark.parametrize(
        "sql,expected_filters",
        [
            # Happy path: WHERE clauses
            ("SELECT * FROM users WHERE id = 1", ["id = 1"]),
            (
                "SELECT * FROM users WHERE age > 18 AND status = 'active'",
                ["age > 18", "status = 'active'"],
            ),
            (
                "SELECT * FROM users WHERE name LIKE 'John%' OR email IS NOT NULL",
                ["name LIKE 'John%'", "email IS NOT NULL"],
            ),
            # With GROUP BY
            (
                "SELECT dept, COUNT(*) FROM employees WHERE salary > 50000 GROUP BY dept",
                ["salary > 50000"],
            ),
            # With ORDER BY
            (
                "SELECT * FROM orders WHERE total > 100 ORDER BY date DESC",
                ["total > 100"],
            ),
            # With LIMIT
            (
                "SELECT * FROM products WHERE category = 'electronics' LIMIT 10",
                ["category = 'electronics'"],
            ),
            # Edge cases: no WHERE clause
            ("SELECT * FROM users", []),
            ("SELECT * FROM users ORDER BY id", []),
            (None, []),
            ("", []),
            # Complex multi-condition WHERE
            (
                "SELECT * FROM users WHERE a=1 AND b=2 AND c=3 GROUP BY dept",
                ["a=1", "b=2", "c=3"],
            ),
        ],
        ids=[
            "simple_where",
            "and_conditions",
            "or_conditions",
            "where_with_group_by",
            "where_with_order_by",
            "where_with_limit",
            "no_where",
            "no_where_with_order",
            "none_sql",
            "empty_sql",
            "multi_conditions",
        ],
    )
    def test_extract_filters_from_sql(self, sql: Any, expected_filters: list[str]) -> None:
        """Test filter extraction from WHERE clauses."""
        result = _extract_filters_from_sql(sql)
        assert result == expected_filters


# =============================================================================
# Tests for _add_provenance_annotation helper
# =============================================================================


class TestAddProvenanceAnnotation:
    """Test provenance annotation addition."""

    @pytest.mark.parametrize(
        "spec,provenance,should_have_annotation",
        [
            # Happy path
            (
                {"type": "bar", "data": []},
                {
                    "tables": ["users"],
                    "filters": ["age > 18"],
                    "executed_sql": "SELECT * FROM users",
                },
                True,
            ),
            # Empty spec - returns as-is because empty dict is falsy
            ({}, {"tables": [], "filters": [], "executed_sql": ""}, False),
            # None spec - returns as-is because None is falsy
            (None, {"tables": ["t1"], "filters": [], "executed_sql": ""}, False),
            # Spec with existing annotation
            (
                {"type": "line", "annotation": {"colors": "red"}},
                {"tables": ["sales"], "filters": [], "executed_sql": ""},
                True,
            ),
            # Spec with one item (truthy)
            (
                {"data": [1, 2, 3]},
                {"tables": ["t1"], "filters": [], "executed_sql": "SELECT * FROM t1"},
                True,
            ),
        ],
        ids=[
            "happy_path",
            "empty_spec",
            "none_spec",
            "existing_annotation",
            "minimal_spec",
        ],
    )
    def test_add_provenance_annotation(
        self,
        spec: Any,
        provenance: dict[str, Any],
        should_have_annotation: bool,
    ) -> None:
        """Test adding provenance annotations to chart specs."""
        result = _add_provenance_annotation(spec, provenance)
        if should_have_annotation:
            assert result is not None
            assert "annotation" in result
            assert "provenance" in result["annotation"]
            assert result["annotation"]["provenance"]["tables"] == provenance["tables"]
        else:
            # For falsy specs (None, {}) the function returns them as-is
            assert result == spec


# =============================================================================
# Tests for provenance_gate main function
# =============================================================================


class TestProvenanceGate:
    """Test the provenance_gate function."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "state_kwargs,expected_status",
        [
            # Happy path: basic query with metrics
            (
                {
                    "thread_id": "t1",
                    "executed_sql": "SELECT COUNT(*) as cnt FROM users",
                    "result_meta": {"cnt": 42},
                },
                "ok",
            ),
            # Happy path: multiple metrics
            (
                {
                    "thread_id": "t1",
                    "executed_sql": "SELECT COUNT(*) as cnt, SUM(amount) as total FROM orders",
                    "result_meta": {"cnt": 10, "total": 500.50},
                },
                "ok",
            ),
            # Happy path: with chart spec
            (
                {
                    "thread_id": "t1",
                    "executed_sql": "SELECT category, COUNT(*) FROM products GROUP BY category",
                    "result_meta": {"count": 100},
                    "chart_spec": {"type": "bar", "data": []},
                },
                "ok",
            ),
            # Happy path: JOIN with multiple tables
            (
                {
                    "thread_id": "t1",
                    "executed_sql": "SELECT u.id, o.total FROM users u JOIN orders o ON u.id = o.user_id",
                    "result_meta": {"total": 1000},
                },
                "ok",
            ),
            # Happy path: with WHERE filters
            (
                {
                    "thread_id": "t1",
                    "executed_sql": "SELECT COUNT(*) as cnt FROM users WHERE age > 18 AND status = 'active'",
                    "result_meta": {"cnt": 150},
                },
                "ok",
            ),
        ],
        ids=[
            "basic_query",
            "multiple_metrics",
            "with_chart_spec",
            "join_multiple_tables",
            "with_filters",
        ],
    )
    def test_provenance_gate_happy_path(
        self, state_kwargs: dict[str, Any], expected_status: str
    ) -> None:
        """Test provenance gate with valid queries."""
        state = OmniState(**state_kwargs)
        result_state = asyncio.run(provenance_gate(state, config={}))

        # Verify guarded dict was populated
        assert result_state.guarded is not None
        assert "provenance_gate" in result_state.guarded
        provenance_result = result_state.guarded["provenance_gate"]

        # Verify status
        assert provenance_result["status"] == expected_status

        # Verify numeric values were tracked (if any in result_meta)
        if state.result_meta:
            numeric_count = sum(1 for v in state.result_meta.values() if _is_numeric(v))
            assert provenance_result["numeric_values_tracked"] == numeric_count

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE users",
            "DELETE FROM orders WHERE id > 100",
            "INSERT INTO users VALUES (1, 'John')",
            "UPDATE accounts SET balance = 0",
            "ALTER TABLE users ADD COLUMN age INT",
            "CREATE TABLE malicious (id INT)",
            "TRUNCATE TABLE important_data",
            "MERGE INTO target USING source",
        ],
        ids=[
            "drop_table",
            "delete_records",
            "insert_records",
            "update_records",
            "alter_schema",
            "create_table",
            "truncate_data",
            "merge_data",
        ],
    )
    def test_provenance_gate_forbidden_operations(self, sql: str) -> None:
        """Test that forbidden SQL operations raise Unsafe."""
        state = OmniState(thread_id="t1", executed_sql=sql)

        with pytest.raises(Unsafe) as exc_info:
            asyncio.run(provenance_gate(state, config={}))

        assert "forbidden operation" in str(exc_info.value.reason).lower()

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "state_kwargs,expected_tracked",
        [
            # Edge case: None result_meta
            (
                {"thread_id": "t1", "executed_sql": "SELECT * FROM users", "result_meta": None},
                0,
            ),
            # Edge case: empty result_meta
            (
                {"thread_id": "t1", "executed_sql": "SELECT * FROM users", "result_meta": {}},
                0,
            ),
            # Edge case: result_meta with non-numeric values
            (
                {
                    "thread_id": "t1",
                    "executed_sql": "SELECT * FROM users",
                    "result_meta": {"name": "John", "status": "active"},
                },
                0,
            ),
            # Edge case: result_meta with mixed numeric and non-numeric
            (
                {
                    "thread_id": "t1",
                    "executed_sql": "SELECT * FROM users",
                    "result_meta": {"count": 42, "name": "John", "total": 100.5},
                },
                2,
            ),
            # Edge case: None executed_sql
            (
                {"thread_id": "t1", "executed_sql": None, "result_meta": {"value": 10}},
                1,
            ),
            # Edge case: empty executed_sql
            (
                {"thread_id": "t1", "executed_sql": "", "result_meta": {"value": 10}},
                1,
            ),
            # Edge case: None chart_spec
            (
                {
                    "thread_id": "t1",
                    "executed_sql": "SELECT * FROM users",
                    "result_meta": {"cnt": 5},
                    "chart_spec": None,
                },
                1,
            ),
            # Edge case: empty chart_spec
            (
                {
                    "thread_id": "t1",
                    "executed_sql": "SELECT * FROM users",
                    "result_meta": {"cnt": 5},
                    "chart_spec": {},
                },
                1,
            ),
        ],
        ids=[
            "none_result_meta",
            "empty_result_meta",
            "non_numeric_result_meta",
            "mixed_result_meta",
            "none_executed_sql",
            "empty_executed_sql",
            "none_chart_spec",
            "empty_chart_spec",
        ],
    )
    def test_provenance_gate_edge_cases(
        self, state_kwargs: dict[str, Any], expected_tracked: int
    ) -> None:
        """Test provenance gate with edge cases (None, empty, etc.)."""
        state = OmniState(**state_kwargs)
        result_state = asyncio.run(provenance_gate(state, config={}))

        # Gate should not raise, but return modified state
        assert result_state.guarded is not None
        provenance_result = result_state.guarded["provenance_gate"]
        assert provenance_result["status"] == "ok"
        assert provenance_result["numeric_values_tracked"] == expected_tracked

    @pytest.mark.unit
    def test_provenance_gate_initializes_guarded_dict(self) -> None:
        """Test that provenance_gate initializes guarded dict if None."""
        state = OmniState(thread_id="t1", executed_sql="SELECT * FROM users")
        assert state.guarded is None

        result_state = asyncio.run(provenance_gate(state, config={}))

        assert result_state.guarded is not None
        assert isinstance(result_state.guarded, dict)
        assert "provenance_gate" in result_state.guarded

    @pytest.mark.unit
    def test_provenance_gate_preserves_existing_guarded(self) -> None:
        """Test that provenance_gate preserves existing guarded data."""
        existing_guarded = {"some_gate": {"result": "previous"}}
        state = OmniState(
            thread_id="t1",
            executed_sql="SELECT * FROM users",
            guarded=existing_guarded.copy(),
        )

        result_state = asyncio.run(provenance_gate(state, config={}))

        # Existing data should still be there
        assert result_state.guarded["some_gate"] == existing_guarded["some_gate"]
        # New data should be added
        assert "provenance_gate" in result_state.guarded

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "sql,expected_tables",
        [
            ("SELECT * FROM users", ["users"]),
            ("SELECT * FROM users u JOIN orders o", ["users", "orders"]),
            ("SELECT * FROM t1 JOIN t2 JOIN t3", ["t1", "t2", "t3"]),
            ("SELECT * FROM users WHERE id = 1", ["users"]),
            (None, []),
            ("", []),
        ],
        ids=[
            "single_table",
            "two_tables_join",
            "three_tables_join",
            "single_table_with_filter",
            "none_sql",
            "empty_sql",
        ],
    )
    def test_provenance_gate_table_extraction(self, sql: Any, expected_tables: list[str]) -> None:
        """Test that provenance_gate correctly extracts table names."""
        state = OmniState(thread_id="t1", executed_sql=sql, result_meta={"cnt": 5})

        result_state = asyncio.run(provenance_gate(state, config={}))

        provenance_result = result_state.guarded["provenance_gate"]
        assert set(provenance_result["tables_identified"]) == set(expected_tables)

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "sql,expected_filter_count",
        [
            ("SELECT * FROM users WHERE id = 1", 1),
            ("SELECT * FROM users WHERE age > 18 AND status = 'active'", 2),
            ("SELECT * FROM users WHERE a=1 AND b=2 AND c=3", 3),
            ("SELECT * FROM users", 0),
            ("SELECT * FROM users ORDER BY id", 0),
            (None, 0),
            ("", 0),
        ],
        ids=[
            "single_filter",
            "two_filters",
            "three_filters",
            "no_filter",
            "no_filter_with_order",
            "none_sql",
            "empty_sql",
        ],
    )
    def test_provenance_gate_filter_extraction(self, sql: Any, expected_filter_count: int) -> None:
        """Test that provenance_gate correctly extracts filter count."""
        state = OmniState(thread_id="t1", executed_sql=sql, result_meta={"value": 10})

        result_state = asyncio.run(provenance_gate(state, config={}))

        provenance_result = result_state.guarded["provenance_gate"]
        assert len(provenance_result["filters_applied"]) == expected_filter_count

    @pytest.mark.unit
    def test_provenance_gate_annotates_chart_spec(self) -> None:
        """Test that provenance_gate adds annotations to chart spec."""
        chart_spec = {"type": "bar", "data": [{"x": "A", "y": 10}]}
        state = OmniState(
            thread_id="t1",
            executed_sql="SELECT category, COUNT(*) as cnt FROM products GROUP BY category",
            result_meta={"cnt": 5},
            chart_spec=chart_spec.copy(),
        )

        result_state = asyncio.run(provenance_gate(state, config={}))

        # Chart spec should be modified with provenance annotation
        assert result_state.chart_spec is not None
        assert "annotation" in result_state.chart_spec
        assert "provenance" in result_state.chart_spec["annotation"]
        provenance = result_state.chart_spec["annotation"]["provenance"]
        assert "tables" in provenance
        assert "filters" in provenance
        assert "sql" in provenance

    @pytest.mark.unit
    def test_provenance_gate_numeric_values_with_provenance(self) -> None:
        """Test that numeric values are tracked with full provenance."""
        state = OmniState(
            thread_id="t1",
            executed_sql="SELECT SUM(amount) as total, COUNT(*) as cnt FROM orders WHERE status = 'completed'",
            result_meta={"total": 5000.50, "cnt": 25},
        )

        result_state = asyncio.run(provenance_gate(state, config={}))

        provenance_result = result_state.guarded["provenance_gate"]
        values = provenance_result["values"]

        assert len(values) == 2
        for value_entry in values:
            assert "name" in value_entry
            assert "value" in value_entry
            assert "tables" in value_entry
            assert "filters" in value_entry
            assert "executed_sql" in value_entry

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "result_meta,expected_count",
        [
            ({"a": 1}, 1),
            ({"a": 1, "b": 2.5}, 2),
            ({"a": 1, "b": "text"}, 1),
            ({"a": "1", "b": "2.5", "c": "text"}, 2),
            ({"a": Decimal("10.5")}, 1),
            ({}, 0),
            ({"a": None}, 0),
            ({"a": [], "b": {}}, 0),
        ],
        ids=[
            "single_int",
            "int_and_float",
            "int_and_string",
            "numeric_strings_and_text",
            "decimal",
            "empty",
            "none_value",
            "collections",
        ],
    )
    def test_provenance_gate_numeric_counting(
        self, result_meta: dict[str, Any], expected_count: int
    ) -> None:
        """Test that only numeric values are counted."""
        state = OmniState(
            thread_id="t1",
            executed_sql="SELECT * FROM data",
            result_meta=result_meta,
        )

        result_state = asyncio.run(provenance_gate(state, config={}))

        provenance_result = result_state.guarded["provenance_gate"]
        assert provenance_result["numeric_values_tracked"] == expected_count

    @pytest.mark.unit
    def test_provenance_gate_complex_sql_with_joins_and_filters(self) -> None:
        """Test provenance gate with complex SQL (JOINs, WHERE, GROUP BY)."""
        sql = """
            SELECT u.id, o.order_date, SUM(o.total) as revenue
            FROM users u
            JOIN orders o ON u.id = o.user_id
            WHERE u.status = 'active' AND o.order_date >= '2024-01-01'
            GROUP BY u.id, o.order_date
            ORDER BY revenue DESC
            LIMIT 10
        """
        state = OmniState(
            thread_id="t1",
            executed_sql=sql,
            result_meta={"revenue": 10000},
        )

        result_state = asyncio.run(provenance_gate(state, config={}))

        provenance_result = result_state.guarded["provenance_gate"]
        # Should extract both tables
        assert "users" in provenance_result["tables_identified"]
        assert "orders" in provenance_result["tables_identified"]
        # Should extract filters
        assert len(provenance_result["filters_applied"]) > 0
        # Should track numeric value
        assert provenance_result["numeric_values_tracked"] == 1

    @pytest.mark.unit
    def test_provenance_gate_idempotent_with_none_guarded(self) -> None:
        """Test that calling provenance_gate multiple times is safe."""
        state = OmniState(
            thread_id="t1",
            executed_sql="SELECT COUNT(*) as cnt FROM users",
            result_meta={"cnt": 100},
        )

        # First call
        state1 = asyncio.run(provenance_gate(state, config={}))
        assert state1.guarded is not None

        # Second call on same state
        state2 = asyncio.run(provenance_gate(state1, config={}))
        assert state2.guarded is not None
        assert "provenance_gate" in state2.guarded
