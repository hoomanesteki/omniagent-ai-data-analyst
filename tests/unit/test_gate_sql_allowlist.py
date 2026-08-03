"""Unit tests for SQL allowlist gate with parametrized test cases."""

import pytest

from omniagent.kernel.gates.exceptions import Unsafe
from omniagent.kernel.gates.sql_allowlist import (
    _contains_keyword,
    _count_sql_statements,
    _has_dml_in_cte,
    _has_union_based_obfuscation,
    _is_select_into,
    _matches_pattern,
    _normalize_sql,
    sql_allowlist_gate,
)
from omniagent.kernel.state import OmniState


class TestNormalizeSql:
    """Tests for SQL normalization (comment removal, whitespace collapse)."""

    @pytest.mark.parametrize(
        "sql,expected",
        [
            # Basic normalization
            ("SELECT * FROM users", "SELECT * FROM users"),
            ("SELECT * FROM users  ", "SELECT * FROM users"),
            ("  SELECT * FROM users", "SELECT * FROM users"),
            # Line comment removal
            ("SELECT * FROM users -- comment", "SELECT * FROM users"),
            ("SELECT * -- comment\nFROM users", "SELECT * FROM users"),
            # Block comment removal
            ("SELECT /* comment */ * FROM users", "SELECT * FROM users"),
            ("SELECT /* multi\nline */ * FROM users", "SELECT * FROM users"),
            # Whitespace collapse
            ("SELECT   *   FROM   users", "SELECT * FROM users"),
            ("SELECT\n*\nFROM\nusers", "SELECT * FROM users"),
            # Combined: comments + whitespace
            ("SELECT * -- comment\n  FROM users  ", "SELECT * FROM users"),
            # Nested block comments
            ("SELECT /* c1 */ * /* c2 */ FROM users", "SELECT * FROM users"),
        ],
    )
    def test_normalize_sql(self, sql: str, expected: str) -> None:
        """Test SQL normalization removes comments and normalizes whitespace."""
        result = _normalize_sql(sql)
        assert result == expected

    def test_normalize_empty_string(self) -> None:
        """Test normalization of empty string."""
        assert _normalize_sql("") == ""

    def test_normalize_only_comments(self) -> None:
        """Test normalization of SQL that is only comments."""
        result = _normalize_sql("-- comment\n/* block */")
        assert result == ""


class TestCountSqlStatements:
    """Tests for SQL statement counting (semicolon-delimited)."""

    @pytest.mark.parametrize(
        "sql,expected_count",
        [
            # Single statements
            ("SELECT * FROM users", 1),
            ("SELECT * FROM users;", 1),
            # Multiple statements
            ("SELECT * FROM users; SELECT * FROM orders", 2),
            ("SELECT * FROM users; SELECT * FROM orders;", 2),
            # Edge cases
            ("", 0),
            (";", 0),  # Only semicolon
            (";;", 0),  # Multiple semicolons
            ("SELECT * FROM users;;;", 1),  # Trailing semicolons
            (";;;SELECT * FROM users", 1),  # Leading semicolons
            # Three statements
            ("SELECT * FROM users; SELECT * FROM orders; SELECT * FROM products", 3),
            ("SELECT * FROM users; SELECT * FROM orders; SELECT * FROM products;", 3),
        ],
    )
    def test_count_sql_statements(self, sql: str, expected_count: int) -> None:
        """Test SQL statement counting."""
        result = _count_sql_statements(sql)
        assert result == expected_count


class TestContainsKeyword:
    """Tests for keyword detection with word boundaries."""

    @pytest.mark.parametrize(
        "sql,keyword,expected",
        [
            # Exact matches
            ("DROP TABLE users", "DROP", True),
            ("drop table users", "DROP", True),
            ("DrOp TABLE users", "DROP", True),
            # Word boundaries (should not match substrings)
            ("DROPS TABLE users", "DROP", False),
            ("AIRDROP TABLE users", "DROP", False),
            # Various keywords
            ("CREATE TABLE users", "CREATE", True),
            ("ALTER TABLE users", "ALTER", True),
            ("DELETE FROM users", "DELETE", True),
            ("INSERT INTO users", "INSERT", True),
            ("UPDATE users", "UPDATE", True),
            ("TRUNCATE TABLE users", "TRUNCATE", True),
            # Not present
            ("SELECT * FROM users", "DROP", False),
            ("SELECT * FROM users", "CREATE", False),
            # Edge cases
            ("", "DROP", False),
            ("SELECT", "SELECT", True),
        ],
    )
    def test_contains_keyword(self, sql: str, keyword: str, expected: bool) -> None:
        """Test keyword detection with word boundaries."""
        result = _contains_keyword(sql, keyword)
        assert result is expected


class TestHasDmlInCte:
    """Tests for DML detection inside CTEs."""

    @pytest.mark.parametrize(
        "sql,expected",
        [
            # No CTE at all
            ("SELECT * FROM users", False),
            # CTE with SELECT only (safe)
            ("WITH user_data AS (SELECT * FROM users) SELECT * FROM user_data", False),
            # CTE with INSERT (unsafe)
            ("WITH cte AS (INSERT INTO users SELECT * FROM staging) SELECT * FROM cte", True),
            # CTE with UPDATE (unsafe)
            ("WITH cte AS (UPDATE users SET active=1) SELECT * FROM cte", True),
            # CTE with DELETE (unsafe)
            ("WITH cte AS (DELETE FROM users WHERE active=0) SELECT * FROM cte", True),
            # Case insensitivity
            ("WITH cte AS (insert into users SELECT * FROM staging) SELECT * FROM cte", True),
            # DML keyword not in CTE
            ("INSERT INTO users SELECT * FROM staging", False),
        ],
    )
    def test_has_dml_in_cte(self, sql: str, expected: bool) -> None:
        """Test DML detection inside CTEs."""
        result = _has_dml_in_cte(sql)
        assert result is expected


class TestIsSelectInto:
    """Tests for SELECT INTO pattern detection."""

    @pytest.mark.parametrize(
        "sql,expected",
        [
            # SELECT INTO (unsafe)
            ("SELECT * INTO new_table FROM users", True),
            ("SELECT id, name INTO backup FROM users", True),
            ("SELECT * INTO users_backup FROM users WHERE active=1", True),
            # Case insensitivity
            ("select * into new_table from users", True),
            ("SELECT * INTO new_table FROM users", True),
            # Regular SELECT (safe)
            ("SELECT * FROM users", False),
            ("SELECT * FROM users INTO @var", False),  # INTO variable, not table
            # Other statements with INTO
            ("INSERT INTO users SELECT * FROM staging", False),
            ("DELETE INTO users", False),
            # Edge cases
            ("", False),
            # Multiple INTO in different contexts
            ("SELECT * INTO table1 FROM users; SELECT * INTO table2 FROM orders", True),
        ],
    )
    def test_is_select_into(self, sql: str, expected: bool) -> None:
        """Test SELECT INTO pattern detection."""
        result = _is_select_into(sql)
        assert result is expected


class TestHasUnionBasedObfuscation:
    """Tests for UNION-based obfuscation pattern detection."""

    @pytest.mark.parametrize(
        "sql,expected",
        [
            # Safe patterns: single UNION
            ("SELECT * FROM users UNION SELECT * FROM archive", False),
            # Safe patterns: 2 UNIONs without EXCEPT/INTERSECT
            ("SELECT * FROM a UNION SELECT * FROM b UNION SELECT * FROM c", False),
            # Unsafe: 3+ UNIONs with EXCEPT (obfuscation - > 2 means 3 or more UNIONs)
            (
                "SELECT * FROM a UNION SELECT * FROM b UNION SELECT * FROM c UNION SELECT * FROM d EXCEPT SELECT * FROM blacklist",
                True,
            ),
            # Unsafe: 3+ UNIONs with INTERSECT (obfuscation)
            (
                "SELECT * FROM a UNION SELECT * FROM b UNION SELECT * FROM c UNION SELECT * FROM d INTERSECT SELECT * FROM whitelist",
                True,
            ),
            # Safe: exactly 2 UNIONs with EXCEPT (only 2 UNIONs, not > 2)
            ("SELECT * FROM a UNION SELECT * FROM b EXCEPT SELECT * FROM blacklist", False),
            # Safe: EXCEPT/INTERSECT without multiple UNIONs
            ("SELECT * FROM a EXCEPT SELECT * FROM blacklist", False),
            # No UNION/EXCEPT/INTERSECT
            ("SELECT * FROM users WHERE active=1", False),
            # Case insensitivity with 3+ UNIONs and EXCEPT
            (
                "select * from a union select * from b union select * from c union select * from d except select * from x",
                True,
            ),
        ],
    )
    def test_has_union_based_obfuscation(self, sql: str, expected: bool) -> None:
        """Test UNION-based obfuscation pattern detection."""
        result = _has_union_based_obfuscation(sql)
        assert result is expected


class TestMatchesPattern:
    """Tests for custom regex pattern matching."""

    @pytest.mark.parametrize(
        "sql,pattern,expected",
        [
            # Valid patterns
            ("SELECT * FROM users", r"FROM", True),
            ("SELECT * FROM users", r"users", True),
            ("SELECT * FROM users", r"^SELECT", True),
            ("SELECT * FROM users", r"users$", True),
            # Case insensitivity
            ("SELECT * FROM users", r"select", True),
            ("select * from users", r"FROM", True),
            # No match
            ("SELECT * FROM users", r"DROP", False),
            ("SELECT * FROM users", r"^DELETE", False),
            # Complex patterns
            ("SELECT * FROM users WHERE id > 100", r"id\s*>\s*\d+", True),
            # Invalid regex (should return False, not raise)
            ("SELECT * FROM users", r"[invalid", False),
            # Empty pattern
            ("SELECT * FROM users", r"", True),  # Empty pattern matches everything
        ],
    )
    def test_matches_pattern(self, sql: str, pattern: str, expected: bool) -> None:
        """Test custom regex pattern matching."""
        result = _matches_pattern(sql, pattern)
        assert result is expected


class TestSqlAllowlistGateHappyPath:
    """Tests for safe SQL queries that pass the allowlist gate."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql",
        [
            # Basic SELECT queries
            "SELECT * FROM users",
            "SELECT id, name FROM users WHERE active=1",
            "SELECT COUNT(*) FROM users",
            "SELECT * FROM users JOIN orders ON users.id=orders.user_id",
            # Complex queries
            "WITH user_counts AS (SELECT user_id, COUNT(*) as cnt FROM orders GROUP BY user_id) SELECT * FROM user_counts",
            "SELECT * FROM users WHERE id IN (SELECT DISTINCT user_id FROM orders)",
            "SELECT * FROM users UNION SELECT * FROM archive",
            # CTEs with multiple SELECT
            "WITH cte1 AS (SELECT * FROM users), cte2 AS (SELECT * FROM cte1 WHERE active=1) SELECT * FROM cte2",
            # Queries with comments
            "SELECT * -- get all users\nFROM users",
            "SELECT /* multi\nline\ncomment */ * FROM users",
            # Edge cases: empty/None SQL
            "",
        ],
    )
    async def test_safe_queries_pass(self, sql: str) -> None:
        """Test that safe SQL queries pass validation."""
        state = OmniState(executed_sql=sql)
        result = await sql_allowlist_gate(state, config={})
        # Should return the state unchanged (or with guarded populated)
        assert result is not None
        assert result.executed_sql == sql

    @pytest.mark.asyncio
    async def test_none_sql_passes(self) -> None:
        """Test that None SQL is handled gracefully."""
        state = OmniState(executed_sql=None)
        result = await sql_allowlist_gate(state, config={})
        assert result is not None

    @pytest.mark.asyncio
    async def test_default_config_applies(self) -> None:
        """Test that default config is applied when not specified."""
        state = OmniState(executed_sql="SELECT * FROM users")
        result = await sql_allowlist_gate(state, config={})
        assert result is not None
        # Verify defaults were used (max_statements=1 passed)


class TestSqlAllowlistGateBlockedKeywords:
    """Tests for blocking dangerous SQL keywords."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql,keyword",
        [
            ("DROP TABLE users", "DROP"),
            ("CREATE TABLE users (id INT)", "CREATE"),
            ("ALTER TABLE users ADD COLUMN name VARCHAR", "ALTER"),
            ("DELETE FROM users WHERE active=0", "DELETE"),
            ("INSERT INTO users SELECT * FROM staging", "INSERT"),
            ("UPDATE users SET active=1", "UPDATE"),
            ("TRUNCATE TABLE users", "TRUNCATE"),
            # Case insensitivity
            ("drop table users", "DROP"),
            ("create table users", "CREATE"),
        ],
    )
    async def test_blocked_keywords_rejected(self, sql: str, keyword: str) -> None:
        """Test that blocked keywords are rejected."""
        state = OmniState(executed_sql=sql)
        with pytest.raises(Unsafe) as exc_info:
            await sql_allowlist_gate(state, config={})
        assert keyword in exc_info.value.reason
        assert "not allowed" in exc_info.value.reason

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql",
        [
            "DROPS TABLE users",  # DROP as substring, not word
            "CREATES TABLE users",
            "DELETES FROM users",
            "INSERTS INTO users",
            "UPDATES users",
        ],
    )
    async def test_keyword_substrings_pass(self, sql: str) -> None:
        """Test that keyword substrings (word boundary misses) pass."""
        state = OmniState(executed_sql=sql)
        # These should not raise because the keyword regex uses word boundaries
        result = await sql_allowlist_gate(state, config={})
        assert result is not None

    @pytest.mark.asyncio
    async def test_custom_blocked_keywords(self) -> None:
        """Test custom blocked keywords configuration."""
        config = {"blocked_keywords": ["GRANT", "REVOKE"]}
        state = OmniState(executed_sql="GRANT SELECT ON users TO public")
        with pytest.raises(Unsafe) as exc_info:
            await sql_allowlist_gate(state, config=config)
        assert "GRANT" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_empty_blocked_keywords(self) -> None:
        """Test that empty blocked keywords allows all keywords."""
        config = {"blocked_keywords": []}
        # This should not raise for normal queries
        state = OmniState(executed_sql="SELECT * FROM users")
        result = await sql_allowlist_gate(state, config=config)
        assert result is not None


class TestSqlAllowlistGateMultipleStatements:
    """Tests for blocking multiple SQL statements."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM users; SELECT * FROM orders",
            "SELECT * FROM users; SELECT * FROM orders; SELECT * FROM products",
            "SELECT * FROM users ; SELECT * FROM orders",  # With spaces around semicolon
        ],
    )
    async def test_multiple_statements_rejected(self, sql: str) -> None:
        """Test that multiple SQL statements are rejected."""
        state = OmniState(executed_sql=sql)
        with pytest.raises(Unsafe) as exc_info:
            await sql_allowlist_gate(state, config={})
        assert "Multiple SQL statements" in exc_info.value.reason
        assert "only single queries" in exc_info.value.reason.lower()

    @pytest.mark.asyncio
    async def test_single_statement_with_semicolon_passes(self) -> None:
        """Test that single statement with trailing semicolon passes."""
        state = OmniState(executed_sql="SELECT * FROM users;")
        result = await sql_allowlist_gate(state, config={})
        assert result is not None

    @pytest.mark.asyncio
    async def test_custom_max_statements(self) -> None:
        """Test custom max_statements configuration."""
        config = {"max_statements": 2}
        # 2 statements should pass
        state = OmniState(executed_sql="SELECT * FROM users; SELECT * FROM orders")
        result = await sql_allowlist_gate(state, config=config)
        assert result is not None

        # 3 statements should fail
        state = OmniState(
            executed_sql="SELECT * FROM users; SELECT * FROM orders; SELECT * FROM products"
        )
        with pytest.raises(Unsafe) as exc_info:
            await sql_allowlist_gate(state, config=config)
        assert "Multiple SQL statements" in exc_info.value.reason


class TestSqlAllowlistGateDMLInCTE:
    """Tests for blocking DML operations inside CTEs."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql",
        [
            "WITH cte AS (INSERT INTO users SELECT * FROM staging) SELECT * FROM cte",
            "WITH cte AS (UPDATE users SET active=1) SELECT * FROM cte",
            "WITH cte AS (DELETE FROM users WHERE active=0) SELECT * FROM cte",
            # Case insensitivity
            "with cte as (insert into users select * from staging) select * from cte",
        ],
    )
    async def test_dml_in_cte_rejected(self, sql: str) -> None:
        """Test that DML operations inside CTEs are rejected."""
        state = OmniState(executed_sql=sql)
        with pytest.raises(Unsafe) as exc_info:
            await sql_allowlist_gate(state, config={})
        # Note: These are caught by the blocked_keywords check first,
        # not by the DML-in-CTE check
        assert "not allowed" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_select_in_cte_passes(self) -> None:
        """Test that SELECT queries inside CTEs pass."""
        state = OmniState(executed_sql="WITH cte AS (SELECT * FROM users) SELECT * FROM cte")
        result = await sql_allowlist_gate(state, config={})
        assert result is not None

    @pytest.mark.asyncio
    async def test_dml_in_cte_specific_check(self) -> None:
        """Test DML-in-CTE check specifically (without blocked_keywords interference)."""
        # Use INSERT as a custom keyword to avoid the default block
        # but keep reject_cte_with_dml enabled to test line 65
        config = {"reject_cte_with_dml": True, "blocked_keywords": []}
        state = OmniState(
            executed_sql="WITH cte AS (INSERT INTO users SELECT * FROM staging) SELECT * FROM cte"
        )
        # Should raise on the DML-in-CTE check
        with pytest.raises(Unsafe) as exc_info:
            await sql_allowlist_gate(state, config=config)
        assert "DML operations" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_reject_cte_with_dml_disabled(self) -> None:
        """Test disabling DML-in-CTE check."""
        config = {"reject_cte_with_dml": False, "blocked_keywords": []}
        state = OmniState(
            executed_sql="WITH cte AS (INSERT INTO users SELECT * FROM staging) SELECT * FROM cte"
        )
        # With blocked_keywords empty and reject_cte_with_dml=False, should not raise
        result = await sql_allowlist_gate(state, config=config)
        assert result is not None


class TestSqlAllowlistGateSelectInto:
    """Tests for blocking SELECT INTO statements."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * INTO new_table FROM users",
            "SELECT id, name INTO backup FROM users WHERE active=1",
            "SELECT COUNT(*) INTO result FROM users",
            # Case insensitivity
            "select * into new_table from users",
        ],
    )
    async def test_select_into_rejected(self, sql: str) -> None:
        """Test that SELECT INTO statements are rejected."""
        state = OmniState(executed_sql=sql)
        with pytest.raises(Unsafe) as exc_info:
            await sql_allowlist_gate(state, config={})
        assert "SELECT INTO" in exc_info.value.reason
        assert "not allowed" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_regular_select_passes(self) -> None:
        """Test that regular SELECT queries pass."""
        state = OmniState(executed_sql="SELECT * FROM users INTO @var")
        result = await sql_allowlist_gate(state, config={})
        assert result is not None


class TestSqlAllowlistGateDynamicSql:
    """Tests for blocking EXEC/EXECUTE statements."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql",
        [
            "EXEC sp_executesql",
            "EXECUTE immediate 'SELECT * FROM users'",
            "exec sp_executesql 'SELECT * FROM users'",
            # Case insensitivity
            "execute sp_procedure",
        ],
    )
    async def test_exec_execute_rejected(self, sql: str) -> None:
        """Test that dynamic SQL execution (EXEC/EXECUTE) is rejected."""
        state = OmniState(executed_sql=sql)
        with pytest.raises(Unsafe) as exc_info:
            await sql_allowlist_gate(state, config={})
        assert "Dynamic SQL" in exc_info.value.reason or "EXEC" in exc_info.value.reason


class TestSqlAllowlistGateUnionObfuscation:
    """Tests for blocking suspicious UNION patterns."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql",
        [
            # 3+ UNIONs with EXCEPT (obfuscation - > 2 means 3 or more)
            "SELECT * FROM a UNION SELECT * FROM b UNION SELECT * FROM c UNION SELECT * FROM d EXCEPT SELECT * FROM blacklist",
            # 3+ UNIONs with INTERSECT (obfuscation)
            "SELECT * FROM a UNION SELECT * FROM b UNION SELECT * FROM c UNION SELECT * FROM d INTERSECT SELECT * FROM whitelist",
            # Case insensitivity with 3+ UNIONs
            "select * from a union select * from b union select * from c union select * from d except select * from x",
        ],
    )
    async def test_union_obfuscation_rejected(self, sql: str) -> None:
        """Test that suspicious UNION patterns are rejected."""
        state = OmniState(executed_sql=sql)
        with pytest.raises(Unsafe) as exc_info:
            await sql_allowlist_gate(state, config={})
        assert "UNION" in exc_info.value.reason or "unsafe" in exc_info.value.reason.lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM a UNION SELECT * FROM b",
            "SELECT * FROM a UNION SELECT * FROM b UNION SELECT * FROM c",
            "SELECT * FROM a UNION SELECT * FROM b EXCEPT SELECT * FROM blacklist",  # 2 UNIONs, safe
        ],
    )
    async def test_safe_union_patterns_pass(self, sql: str) -> None:
        """Test that safe UNION patterns pass validation."""
        state = OmniState(executed_sql=sql)
        result = await sql_allowlist_gate(state, config={})
        assert result is not None


class TestSqlAllowlistGateCustomBlocklist:
    """Tests for custom blocklist patterns."""

    @pytest.mark.asyncio
    async def test_custom_pattern_rejected(self) -> None:
        """Test that custom regex patterns are applied."""
        config = {"custom_blocklist": [r"sys\w*\.", r"information_schema"]}
        state = OmniState(executed_sql="SELECT * FROM sys.tables")
        with pytest.raises(Unsafe) as exc_info:
            await sql_allowlist_gate(state, config=config)
        assert "blocked pattern" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_multiple_custom_patterns(self) -> None:
        """Test multiple custom blocklist patterns."""
        config = {
            "custom_blocklist": [
                r"sys\w*\.",
                r"pg_\w+",
                r"sqlite_\w+",
            ]
        }
        # Should fail on pg_ pattern
        state = OmniState(executed_sql="SELECT * FROM pg_tables")
        with pytest.raises(Unsafe) as exc_info:
            await sql_allowlist_gate(state, config=config)
        assert "blocked pattern" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_invalid_regex_pattern_safe(self) -> None:
        """Test that invalid regex patterns don't crash (graceful degradation)."""
        config = {"custom_blocklist": [r"[invalid"]}  # Invalid regex
        state = OmniState(executed_sql="SELECT * FROM users")
        # Should not raise; invalid regex is treated as no-match
        result = await sql_allowlist_gate(state, config=config)
        assert result is not None

    @pytest.mark.asyncio
    async def test_empty_custom_blocklist(self) -> None:
        """Test empty custom blocklist."""
        config = {"custom_blocklist": []}
        state = OmniState(executed_sql="SELECT * FROM users")
        result = await sql_allowlist_gate(state, config=config)
        assert result is not None


class TestSqlAllowlistGateEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_empty_sql_string(self) -> None:
        """Test that empty SQL string is handled gracefully."""
        state = OmniState(executed_sql="")
        result = await sql_allowlist_gate(state, config={})
        assert result is not None

    @pytest.mark.asyncio
    async def test_none_sql(self) -> None:
        """Test that None SQL is handled gracefully."""
        state = OmniState(executed_sql=None)
        result = await sql_allowlist_gate(state, config={})
        assert result is not None

    @pytest.mark.asyncio
    async def test_non_string_sql(self) -> None:
        """Test that non-string SQL is handled gracefully."""
        state = OmniState(executed_sql=123)  # type: ignore
        result = await sql_allowlist_gate(state, config={})
        assert result is not None

    @pytest.mark.asyncio
    async def test_sql_with_only_comments(self) -> None:
        """Test SQL that contains only comments."""
        state = OmniState(executed_sql="-- just a comment\n/* block comment */")
        result = await sql_allowlist_gate(state, config={})
        assert result is not None

    @pytest.mark.asyncio
    async def test_sql_with_excessive_whitespace(self) -> None:
        """Test SQL with excessive whitespace."""
        state = OmniState(executed_sql="SELECT\n\n  *\n\n  FROM\n\n  users  ")
        result = await sql_allowlist_gate(state, config={})
        assert result is not None

    @pytest.mark.asyncio
    async def test_unicode_in_sql(self) -> None:
        """Test SQL with unicode characters."""
        state = OmniState(executed_sql="SELECT * FROM users WHERE name = '日本語'")
        result = await sql_allowlist_gate(state, config={})
        assert result is not None

    @pytest.mark.asyncio
    async def test_sql_with_string_literals_containing_keywords(self) -> None:
        """Test SQL with keywords inside string literals (known limitation)."""
        # Note: Keywords inside string literals are still caught by the simple
        # keyword matching (no string parsing). This is a known limitation.
        state = OmniState(
            executed_sql="SELECT * FROM logs WHERE message = 'DROP TABLE was attempted'"
        )
        # Will raise because 'DROP' is detected even inside string
        with pytest.raises(Unsafe):
            await sql_allowlist_gate(state, config={})


class TestSqlAllowlistGateStatePassing:
    """Tests for state modification and passing."""

    @pytest.mark.asyncio
    async def test_state_unchanged_on_pass(self) -> None:
        """Test that state is returned unchanged when validation passes."""
        original_sql = "SELECT * FROM users"
        state = OmniState(
            executed_sql=original_sql,
            thread_id="test_123",
            principal={"tenant": "acme"},
        )
        result = await sql_allowlist_gate(state, config={})
        assert result.executed_sql == original_sql
        assert result.thread_id == "test_123"
        assert result.principal == {"tenant": "acme"}

    @pytest.mark.asyncio
    async def test_exception_includes_reason(self) -> None:
        """Test that Unsafe exceptions include descriptive reasons."""
        state = OmniState(executed_sql="DROP TABLE users")
        with pytest.raises(Unsafe) as exc_info:
            await sql_allowlist_gate(state, config={})
        # Exception should have a descriptive reason
        assert exc_info.value.reason
        assert len(exc_info.value.reason) > 0
        assert str(exc_info.value) == exc_info.value.reason


class TestSqlAllowlistGateIntegration:
    """Integration tests for complex scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql,should_fail",
        [
            # Real-world scenarios
            ("SELECT * FROM customer_data WHERE customer_id = 123", False),
            ("SELECT COUNT(*) as total FROM orders GROUP BY region", False),
            (
                "WITH monthly_sales AS (SELECT DATE_TRUNC('month', created_at) as month, SUM(amount) as total FROM orders GROUP BY 1) SELECT * FROM monthly_sales",
                False,
            ),
            # Unsafe scenarios
            ("SELECT * FROM users; DROP TABLE sensitive_data", True),
            ("CREATE TEMP TABLE temp AS SELECT * FROM users", True),
            ("DELETE FROM audit_log", True),
        ],
    )
    async def test_real_world_scenarios(self, sql: str, should_fail: bool) -> None:
        """Test real-world SQL query scenarios."""
        state = OmniState(executed_sql=sql)
        if should_fail:
            with pytest.raises(Unsafe):
                await sql_allowlist_gate(state, config={})
        else:
            result = await sql_allowlist_gate(state, config={})
            assert result is not None

    @pytest.mark.asyncio
    async def test_multiple_violations_first_caught(self) -> None:
        """Test that first violation is caught (not all violations)."""
        # This has both multiple statements AND DROP
        state = OmniState(executed_sql="DROP TABLE users; SELECT * FROM orders")
        with pytest.raises(Unsafe):
            await sql_allowlist_gate(state, config={})
        # Should raise on first check (statements count or keyword)
