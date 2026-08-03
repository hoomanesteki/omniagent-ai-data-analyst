"""Parametrized unit tests for PII masking gate."""

import asyncio
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from omniagent.kernel.gates.pii_mask import (
    _get_pii_columns,
    _mask_pii_value,
    _mask_result_table,
    pii_mask_gate,
)
from omniagent.kernel.state import OmniState


def _run_async(coro):
    """Helper to run async functions in tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================================
# Tests for _mask_pii_value (pattern-based masking)
# ============================================================================


class TestMaskPiiValue:
    """Test cases for individual PII value masking."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            # Happy path: email addresses
            ("john.doe@example.com", "***@***.***"),
            ("user-tag@domain.co.uk", "***@***.***"),
            ("test.123@test-domain.com", "***@***.***"),
            # Happy path: phone numbers
            ("(123) 456-7890", "***-***-****"),
            ("123-456-7890", "***-***-****"),
            ("1234567890", "***-***-****"),
            ("+1-555-123-4567", "***-***-****"),
            ("+1 (555) 123-4567", "***-***-****"),
            # Happy path: SSN
            ("123-45-6789", "***-**-****"),
            # Happy path: credit card
            ("4532-1488-0343-6467", "****-****-****-****"),
            ("4532 1488 0343 6467", "****-****-****-****"),
            # Edge cases: None value
            (None, None),
            # Edge cases: empty/whitespace string
            ("", ""),
            ("   ", ""),
            # Non-PII values (should pass through)
            ("John Doe", "John Doe"),
            ("12345", "12345"),
            ("normal text", "normal text"),
            ("user@localhost", "user@localhost"),  # Missing TLD
            ("user+tag@domain.com", "***@***.***"),  # tagged address is still PII
            ("+44 20 7946 0958", "+44 20 7946 0958"),  # Phone with multiple spaces
            ("4532148803436467", "4532148803436467"),  # CC plain digits without separators
        ],
        ids=[
            "email_simple",
            "email_dashed_domain",
            "email_complex_domain",
            "phone_us_parens",
            "phone_us_dashes",
            "phone_us_plain",
            "phone_intl_plus",
            "phone_us_intl_format",
            "ssn_pattern",
            "cc_dashes",
            "cc_spaces",
            "none_value",
            "empty_string",
            "whitespace_string",
            "plain_text",
            "numeric_string",
            "normal_text",
            "email_no_tld",
            "email_with_plus",
            "phone_intl_multiple_spaces",
            "cc_plain_no_separator",
        ],
    )
    def test_mask_pii_value(self, value: Any, expected: Any) -> None:
        """Test PII value masking with various patterns."""
        result = _mask_pii_value(value)
        assert result == expected


# ============================================================================
# Tests for _get_pii_columns (catalog parsing)
# ============================================================================


class TestGetPiiColumns:
    """Test cases for extracting PII column metadata from semantic provider."""

    @pytest.mark.parametrize(
        "semantic_provider,dataset_id,expected",
        [
            # Happy path: nested table structure with PII columns
            (
                Mock(
                    catalog=Mock(
                        return_value={
                            "tables": {
                                "users": {
                                    "columns": {
                                        "email": {"pii": True},
                                        "name": {"pii": False},
                                        "phone": {"pii": True},
                                    }
                                }
                            }
                        }
                    )
                ),
                "dataset1",
                {"email": True, "phone": True},
            ),
            # Happy path: flat column structure
            (
                Mock(
                    catalog=Mock(
                        return_value={
                            "columns": {
                                "email": {"pii": True},
                                "ssn": {"pii": True},
                                "age": {"pii": False},
                            }
                        }
                    )
                ),
                "dataset1",
                {"email": True, "ssn": True},
            ),
            # Happy path: multiple tables with PII
            (
                Mock(
                    catalog=Mock(
                        return_value={
                            "tables": {
                                "users": {
                                    "columns": {
                                        "email": {"pii": True},
                                    }
                                },
                                "employees": {
                                    "columns": {
                                        "ssn": {"pii": True},
                                        "salary": {"pii": False},
                                    }
                                },
                            }
                        }
                    )
                ),
                "dataset1",
                {"email": True, "ssn": True},
            ),
            # Edge case: no PII columns marked
            (
                Mock(
                    catalog=Mock(
                        return_value={
                            "tables": {
                                "public": {
                                    "columns": {
                                        "id": {"pii": False},
                                        "name": {"pii": False},
                                    }
                                }
                            }
                        }
                    )
                ),
                "dataset1",
                {},
            ),
            # Edge case: empty catalog
            (Mock(catalog=Mock(return_value={})), "dataset1", {}),
            # Edge case: catalog is None
            (Mock(catalog=Mock(return_value=None)), "dataset1", {}),
            # Edge case: malformed structure (missing columns key)
            (
                Mock(
                    catalog=Mock(
                        return_value={
                            "tables": {
                                "users": {
                                    "fields": {"email": {"pii": True}}  # Wrong key
                                }
                            }
                        }
                    )
                ),
                "dataset1",
                {},
            ),
            # Edge case: None semantic provider
            (None, "dataset1", {}),
            # Edge case: semantic provider raises exception
            (Mock(catalog=Mock(side_effect=Exception("Catalog error"))), "dataset1", {}),
            # Happy path: mixed True and None values
            (
                Mock(
                    catalog=Mock(
                        return_value={
                            "tables": {
                                "users": {
                                    "columns": {
                                        "email": {"pii": True},
                                        "phone": {"pii": None},  # Explicitly None
                                        "address": {},  # Missing pii key
                                    }
                                }
                            }
                        }
                    )
                ),
                "dataset1",
                {"email": True},
            ),
        ],
        ids=[
            "nested_table_structure",
            "flat_column_structure",
            "multiple_tables_with_pii",
            "no_pii_columns_marked",
            "empty_catalog",
            "catalog_none",
            "malformed_structure",
            "none_semantic_provider",
            "semantic_provider_error",
            "mixed_pii_values",
        ],
    )
    def test_get_pii_columns(self, semantic_provider: Any, dataset_id: str, expected: dict) -> None:
        """Test PII column extraction from semantic provider catalog."""
        result = _get_pii_columns(semantic_provider, dataset_id)
        assert result == expected


# ============================================================================
# Tests for _mask_result_table (table masking)
# ============================================================================


class TestMaskResultTable:
    """Test cases for masking result tables (Arrow, DataFrame, dict list)."""

    @pytest.mark.parametrize(
        "result_table,pii_columns,expected_type",
        [
            # Happy path: list of dicts
            (
                [
                    {"id": 1, "email": "john@example.com", "name": "John"},
                    {"id": 2, "email": "jane@example.com", "name": "Jane"},
                ],
                {"email": True},
                list,
            ),
            # Happy path: DataFrame-like (mock)
            (
                MagicMock(
                    **{
                        "copy.return_value": MagicMock(
                            columns=["id", "email", "name"],
                            **{
                                "apply.side_effect": [
                                    MagicMock(
                                        name="masked_email",
                                        __getitem__=MagicMock(return_value="***@***.***"),
                                    )
                                ]
                            },
                        ),
                        "__getitem__": MagicMock(),
                    }
                ),
                {"email": True},
                type(MagicMock()),
            ),
            # Edge case: no PII columns
            (
                [{"id": 1, "name": "John"}],
                {},
                list,
            ),
            # Edge case: None result table
            (None, {"email": True}, type(None)),
            # Edge case: empty list
            ([], {"email": True}, list),
            # Edge case: single dict without PII columns
            (
                [{"id": 1, "name": "John"}],
                {"email": True},  # email not in dict
                list,
            ),
            # Happy path: mixed rows (some with PII, some without)
            (
                [
                    {"id": 1, "email": "john@example.com", "phone": "555-1234"},
                    {"id": 2, "name": "Jane"},  # No PII columns
                    {"id": 3, "email": "bob@example.com"},
                ],
                {"email": True, "phone": True},
                list,
            ),
        ],
        ids=[
            "list_of_dicts_with_pii",
            "dataframe_like",
            "no_pii_columns",
            "none_result_table",
            "empty_list",
            "pii_columns_not_in_data",
            "mixed_rows_with_partial_pii",
        ],
    )
    def test_mask_result_table(
        self, result_table: Any, pii_columns: dict, expected_type: type
    ) -> None:
        """Test result table masking for different table types."""
        if result_table is None or not pii_columns:
            # For None or no PII, should return original
            result = _mask_result_table(result_table, pii_columns)
            assert result == result_table
        else:
            result = _mask_result_table(result_table, pii_columns)
            if isinstance(result_table, list) and isinstance(result, list):
                # Verify list structure is preserved
                assert len(result) == len(result_table)
                # For list of dicts, verify masking occurred
                if pii_columns and result_table and isinstance(result_table[0], dict):
                    for masked_row, orig_row in zip(result, result_table, strict=True):
                        if isinstance(masked_row, dict):
                            # Check that non-PII columns are unchanged
                            for key, val in orig_row.items():
                                if key not in pii_columns:
                                    assert masked_row[key] == val

    def test_mask_result_table_list_of_dicts_masking(self) -> None:
        """Test detailed masking behavior on list of dicts."""
        result_table = [
            {"id": 1, "email": "john@example.com", "name": "John", "phone": "555-1234"},
            {"id": 2, "email": "jane@example.com", "name": "Jane", "phone": "555-5678"},
        ]
        pii_columns = {"email": True, "phone": True}

        masked = _mask_result_table(result_table, pii_columns)

        assert len(masked) == 2
        # Check first row masking
        assert masked[0]["id"] == 1
        assert masked[0]["name"] == "John"  # Non-PII unchanged
        assert masked[0]["email"] == "***@***.***"  # Masked
        assert masked[0]["phone"] == "***-***-****"  # Masked
        # Check second row masking
        assert masked[1]["id"] == 2
        assert masked[1]["name"] == "Jane"
        assert masked[1]["email"] == "***@***.***"
        assert masked[1]["phone"] == "***-***-****"

    def test_mask_result_table_with_non_dict_rows(self) -> None:
        """Test masking behavior when rows are not dicts."""
        result_table = [
            "string_row",
            123,
            {"id": 1, "email": "john@example.com"},
        ]
        pii_columns = {"email": True}

        masked = _mask_result_table(result_table, pii_columns)

        # Non-dict rows should pass through unchanged
        assert masked[0] == "string_row"
        assert masked[1] == 123
        # Dict rows should be masked
        assert masked[2]["email"] == "***@***.***"

    def test_mask_result_table_exception_handling(self) -> None:
        """Test that exceptions during masking return original table."""
        result_table = MagicMock()
        result_table.to_pandas.side_effect = Exception("Masking failed")
        pii_columns = {"email": True}

        # Should return original on exception
        result = _mask_result_table(result_table, pii_columns)
        assert result == result_table


# ============================================================================
# Tests for pii_mask_gate (main gate function)
# ============================================================================


class TestPiiMaskGate:
    """Test cases for the main PII masking gate."""

    @pytest.mark.parametrize(
        "result_ref,dataset_id,pii_columns,expected_status",
        [
            # Happy path: successful masking
            (
                "ref-123",
                "dataset-1",
                {"email": True},
                "masked_successfully",
            ),
            # Violation: no result_ref
            (None, "dataset-1", {}, "no_result_ref"),
            # Violation: no dataset_id
            ("ref-123", "", {}, "no_dataset_id"),
            # Violation: empty dataset_id
            ("ref-123", None, {}, "no_dataset_id"),
            # Edge case: no PII columns found
            ("ref-123", "dataset-1", {}, "no_pii_columns_found"),
            # Violation: dependencies unavailable (no semantic provider)
            ("ref-123", "dataset-1", {"email": True}, "dependencies_unavailable"),
        ],
        ids=[
            "successful_masking",
            "no_result_ref",
            "no_dataset_id",
            "empty_dataset_id",
            "no_pii_columns",
            "dependencies_unavailable",
        ],
    )
    def test_pii_mask_gate_scenarios(
        self,
        result_ref: str | None,
        dataset_id: str | None,
        pii_columns: dict,
        expected_status: str,
    ) -> None:
        """Test PII mask gate in various scenarios."""
        state = OmniState(
            result_ref=result_ref,
            dataset_id=dataset_id,
        )

        if expected_status == "dependencies_unavailable":
            # No semantic provider or result store
            config = {}
        else:
            # Provide dependencies for successful cases
            semantic_provider = Mock(
                catalog=Mock(
                    return_value={
                        "tables": {
                            "users": {"columns": {k: {"pii": True} for k in pii_columns.keys()}}
                        }
                    }
                )
            )
            result_store = Mock()
            result_store.get.return_value = [{"email": "test@example.com", "id": 1}]
            result_store.put.return_value = "ref-masked-123"

            config = {
                "semantic_provider": semantic_provider,
                "result_store": result_store,
                "principal": {"user": "test"},
            }

        result = _run_async(pii_mask_gate(state, config=config))

        assert result.guarded is not None
        assert "pii_mask_gate" in result.guarded
        assert result.guarded["pii_mask_gate"]["status"] == expected_status

    def test_pii_mask_gate_happy_path_with_masking(self) -> None:
        """Test successful PII masking flow with result store."""
        state = OmniState(
            result_ref="ref-original",
            dataset_id="dataset-1",
        )

        # Mock semantic provider
        semantic_provider = Mock(
            catalog=Mock(
                return_value={
                    "tables": {
                        "users": {
                            "columns": {
                                "email": {"pii": True},
                                "phone": {"pii": True},
                                "name": {"pii": False},
                            }
                        }
                    }
                }
            )
        )

        # Mock result table
        result_table = [
            {"id": 1, "email": "john@example.com", "phone": "555-1234", "name": "John"},
        ]

        # Mock result store
        result_store = Mock()
        result_store.get.return_value = result_table
        result_store.put.return_value = "ref-masked-123"

        config = {
            "semantic_provider": semantic_provider,
            "result_store": result_store,
            "principal": {"user": "test"},
        }

        result = _run_async(pii_mask_gate(state, config=config))

        # Verify state was modified
        assert result.result_ref == "ref-masked-123"
        # Verify guarded records success
        assert result.guarded["pii_mask_gate"]["status"] == "masked_successfully"
        assert result.guarded["pii_mask_gate"]["masked"] is True
        assert "email" in result.guarded["pii_mask_gate"]["pii_columns_masked"]
        assert "phone" in result.guarded["pii_mask_gate"]["pii_columns_masked"]
        # Verify assumption was added
        assert any("PII" in a for a in result.assumptions)
        # Verify result store was called correctly
        result_store.get.assert_called_once()
        result_store.put.assert_called_once()

    def test_pii_mask_gate_result_retrieval_failure(self) -> None:
        """Test gate behavior when result retrieval fails."""
        state = OmniState(
            result_ref="ref-123",
            dataset_id="dataset-1",
        )

        semantic_provider = Mock(
            catalog=Mock(return_value={"tables": {"users": {"columns": {"email": {"pii": True}}}}})
        )

        result_store = Mock()
        result_store.get.side_effect = Exception("Storage error")

        config = {
            "semantic_provider": semantic_provider,
            "result_store": result_store,
            "principal": {"user": "test"},
        }

        result = _run_async(pii_mask_gate(state, config=config))

        # Should record failure but not raise
        assert result.guarded["pii_mask_gate"]["status"] == "result_retrieval_failed"
        assert result.guarded["pii_mask_gate"]["masked"] is False
        assert "Storage error" in result.guarded["pii_mask_gate"]["error"]
        # result_ref should remain unchanged
        assert result.result_ref == "ref-123"

    def test_pii_mask_gate_empty_result(self) -> None:
        """Test gate behavior when result table is None."""
        state = OmniState(
            result_ref="ref-123",
            dataset_id="dataset-1",
        )

        semantic_provider = Mock(
            catalog=Mock(return_value={"tables": {"users": {"columns": {"email": {"pii": True}}}}})
        )

        result_store = Mock()
        result_store.get.return_value = None

        config = {
            "semantic_provider": semantic_provider,
            "result_store": result_store,
            "principal": {"user": "test"},
        }

        result = _run_async(pii_mask_gate(state, config=config))

        assert result.guarded["pii_mask_gate"]["status"] == "empty_result"
        assert result.guarded["pii_mask_gate"]["masked"] is False
        assert result.result_ref == "ref-123"

    def test_pii_mask_gate_storage_failure(self) -> None:
        """Test gate behavior when storing masked result fails."""
        state = OmniState(
            result_ref="ref-123",
            dataset_id="dataset-1",
        )

        semantic_provider = Mock(
            catalog=Mock(return_value={"tables": {"users": {"columns": {"email": {"pii": True}}}}})
        )

        result_table = [{"id": 1, "email": "test@example.com"}]

        result_store = Mock()
        result_store.get.return_value = result_table
        result_store.put.side_effect = Exception("Storage full")

        config = {
            "semantic_provider": semantic_provider,
            "result_store": result_store,
            "principal": {"user": "test"},
        }

        result = _run_async(pii_mask_gate(state, config=config))

        # Should record failure
        assert result.guarded["pii_mask_gate"]["status"] == "storage_failed"
        assert result.guarded["pii_mask_gate"]["masked"] is False
        # result_ref should remain unchanged
        assert result.result_ref == "ref-123"

    def test_pii_mask_gate_guarded_dict_initialization(self) -> None:
        """Test that guarded dict is properly initialized if None."""
        state = OmniState(
            result_ref=None,
            dataset_id="dataset-1",
            guarded=None,
        )

        config = {}

        result = _run_async(pii_mask_gate(state, config=config))

        assert result.guarded is not None
        assert isinstance(result.guarded, dict)
        assert "pii_mask_gate" in result.guarded

    def test_pii_mask_gate_with_existing_guarded(self) -> None:
        """Test that existing guarded data is preserved."""
        state = OmniState(
            result_ref=None,
            dataset_id="dataset-1",
            guarded={"previous_gate": {"status": "passed"}},
        )

        config = {}

        result = _run_async(pii_mask_gate(state, config=config))

        # Original guarded entry should remain
        assert "previous_gate" in result.guarded
        assert result.guarded["previous_gate"]["status"] == "passed"
        # New entry should be added
        assert "pii_mask_gate" in result.guarded

    def test_pii_mask_gate_assumptions_added(self) -> None:
        """Test that assumptions are properly added to state."""
        state = OmniState(
            result_ref="ref-123",
            dataset_id="dataset-1",
            assumptions=["existing_assumption"],
        )

        semantic_provider = Mock(
            catalog=Mock(return_value={"tables": {"users": {"columns": {"email": {"pii": True}}}}})
        )

        result_store = Mock()
        result_store.get.return_value = [{"id": 1, "email": "test@example.com"}]
        result_store.put.return_value = "ref-masked"

        config = {
            "semantic_provider": semantic_provider,
            "result_store": result_store,
            "principal": {"user": "test"},
        }

        result = _run_async(pii_mask_gate(state, config=config))

        # Should preserve existing assumptions
        assert "existing_assumption" in result.assumptions
        # Should add new assumption
        assert any("PII" in a for a in result.assumptions)

    def test_pii_mask_gate_no_duplicate_assumptions(self) -> None:
        """Test that duplicate assumptions are not added."""
        assumption = "Result includes masked PII columns (emails, phone numbers, etc.)"
        state = OmniState(
            result_ref="ref-123",
            dataset_id="dataset-1",
            assumptions=[assumption],
        )

        semantic_provider = Mock(
            catalog=Mock(return_value={"tables": {"users": {"columns": {"email": {"pii": True}}}}})
        )

        result_store = Mock()
        result_store.get.return_value = [{"id": 1, "email": "test@example.com"}]
        result_store.put.return_value = "ref-masked"

        config = {
            "semantic_provider": semantic_provider,
            "result_store": result_store,
            "principal": {"user": "test"},
        }

        result = _run_async(pii_mask_gate(state, config=config))

        # Count occurrences of the assumption
        count = sum(1 for a in result.assumptions if a == assumption)
        assert count == 1

    @pytest.mark.parametrize(
        "email_input,expected",
        [
            ("user@example.com", "***@***.***"),
            ("user+tag@sub.example.co.uk", "***@***.***"),
            ("UPPERCASE@EXAMPLE.COM", "***@***.***"),
        ],
    )
    def test_pii_mask_gate_email_masking_variants(self, email_input: str, expected: str) -> None:
        """Test email masking in various formats through the gate."""
        state = OmniState(
            result_ref="ref-123",
            dataset_id="dataset-1",
        )

        semantic_provider = Mock(
            catalog=Mock(return_value={"tables": {"users": {"columns": {"email": {"pii": True}}}}})
        )

        result_table = [{"id": 1, "email": email_input}]

        # Mock put to return a callable that captures the masked table
        def put_side_effect(table, **kwargs):
            # Verify masking was applied
            assert table[0]["email"] == expected
            return "ref-masked"

        result_store = Mock()
        result_store.get.return_value = result_table
        result_store.put.side_effect = put_side_effect

        config = {
            "semantic_provider": semantic_provider,
            "result_store": result_store,
            "principal": {"user": "test"},
        }

        result = _run_async(pii_mask_gate(state, config=config))

        assert result.guarded["pii_mask_gate"]["status"] == "masked_successfully"


# ============================================================================
# Integration-style tests combining multiple components
# ============================================================================


class TestPiiMaskGateIntegration:
    """Integration-style tests for PII masking with multiple components."""

    def test_full_masking_flow_with_multiple_pii_types(self) -> None:
        """Test masking flow with multiple PII types in single result."""
        state = OmniState(
            result_ref="ref-123",
            dataset_id="dataset-1",
        )

        semantic_provider = Mock(
            catalog=Mock(
                return_value={
                    "tables": {
                        "customers": {
                            "columns": {
                                "email": {"pii": True},
                                "phone": {"pii": True},
                                "ssn": {"pii": True},
                                "name": {"pii": False},
                            }
                        }
                    }
                }
            )
        )

        result_table = [
            {
                "id": 1,
                "name": "John Doe",
                "email": "john@example.com",
                "phone": "555-1234",
                "ssn": "123-45-6789",
            },
            {
                "id": 2,
                "name": "Jane Smith",
                "email": "jane@example.com",
                "phone": "555-5678",
                "ssn": "987-65-4321",
            },
        ]

        result_store = Mock()
        result_store.get.return_value = result_table
        result_store.put.return_value = "ref-masked"

        config = {
            "semantic_provider": semantic_provider,
            "result_store": result_store,
            "principal": {"user": "test"},
        }

        result = _run_async(pii_mask_gate(state, config=config))

        # Verify successful masking
        assert result.guarded["pii_mask_gate"]["status"] == "masked_successfully"
        assert result.guarded["pii_mask_gate"]["masked"] is True
        assert len(result.guarded["pii_mask_gate"]["pii_columns_masked"]) == 3

        # Verify put was called with proper TTL
        result_store.put.assert_called_once()
        call_kwargs = result_store.put.call_args.kwargs
        assert call_kwargs.get("ttl_s") == 900

    def test_masking_skipped_when_semantic_provider_error(self) -> None:
        """Test that masking gracefully handles semantic provider errors."""
        state = OmniState(
            result_ref="ref-123",
            dataset_id="dataset-1",
        )

        semantic_provider = Mock()
        semantic_provider.catalog.side_effect = ValueError("Invalid dataset")

        result_store = Mock()
        result_store.get.return_value = [{"id": 1, "email": "test@example.com"}]

        config = {
            "semantic_provider": semantic_provider,
            "result_store": result_store,
            "principal": {"user": "test"},
        }

        result = _run_async(pii_mask_gate(state, config=config))

        # Should gracefully handle and report
        assert result.guarded["pii_mask_gate"]["status"] == "no_pii_columns_found"
        assert result.guarded["pii_mask_gate"]["masked"] is False
        # result_ref should remain unchanged
        assert result.result_ref == "ref-123"

    def test_masking_with_principal_passed_correctly(self) -> None:
        """Test that principal is correctly passed to result store."""
        state = OmniState(
            result_ref="ref-123",
            dataset_id="dataset-1",
        )

        semantic_provider = Mock(
            catalog=Mock(return_value={"tables": {"users": {"columns": {"email": {"pii": True}}}}})
        )

        result_store = Mock()
        result_store.get.return_value = [{"id": 1, "email": "test@example.com"}]
        result_store.put.return_value = "ref-masked"

        principal = {"tenant": "acme", "user": "alice"}
        config = {
            "semantic_provider": semantic_provider,
            "result_store": result_store,
            "principal": principal,
        }

        _run_async(pii_mask_gate(state, config=config))

        # Verify principal was passed to both get and put calls
        result_store.get.assert_called_once_with("ref-123", principal=principal)
        # put call should also have principal
        put_call = result_store.put.call_args
        assert put_call.kwargs["principal"] == principal


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
