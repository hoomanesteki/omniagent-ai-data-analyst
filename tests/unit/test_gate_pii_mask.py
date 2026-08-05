"""Unit tests for the PII masking gate.

The gate masks `state.result_set` in place using two layers: a column-name
match against the semantic layer's declared PII dimensions, and a
value-shape heuristic applied regardless of column name (see pii_mask.py's
module docstring for why neither alone is enough). It runs before
`narrator_node` ever reads `result_set`, so a masked value cannot leak back
out through the narration text either.
"""

import asyncio
from typing import Any
from unittest.mock import Mock

import pytest

from omniagent.kernel.catalog import Catalog, DimensionInfo
from omniagent.kernel.gates.pii_mask import _mask_pii_value, _pii_column_keys, pii_mask_gate
from omniagent.kernel.state import OmniState


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestMaskPiiValue:
    """Value-shape masking, independent of column name."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("john.doe@example.com", "***@***.***"),
            ("user-tag@domain.co.uk", "***@***.***"),
            ("test.123@test-domain.com", "***@***.***"),
            ("(123) 456-7890", "***-***-****"),
            ("123-456-7890", "***-***-****"),
            ("1234567890", "***-***-****"),
            ("+1-555-123-4567", "***-***-****"),
            ("123-45-6789", "***-**-****"),
            ("4532-1488-0343-6467", "****-****-****-****"),
            ("4532 1488 0343 6467", "****-****-****-****"),
            (None, None),
            ("", ""),
            ("John Doe", "John Doe"),
            ("12345", "12345"),
            ("normal text", "normal text"),
            ("user@localhost", "user@localhost"),
            ("user+tag@domain.com", "***@***.***"),
            ("+44 20 7946 0958", "+44 20 7946 0958"),
            ("4532148803436467", "4532148803436467"),
            (42, 42),
            (3.14, 3.14),
        ],
        ids=[
            "email_simple",
            "email_dashed_domain",
            "email_complex_domain",
            "phone_us_parens",
            "phone_us_dashes",
            "phone_us_plain",
            "phone_intl_plus",
            "ssn_pattern",
            "cc_dashes",
            "cc_spaces",
            "none_value",
            "empty_string",
            "plain_text",
            "numeric_string",
            "normal_text",
            "email_no_tld",
            "email_with_plus",
            "phone_intl_multiple_spaces",
            "cc_plain_no_separator",
            "non_string_int",
            "non_string_float",
        ],
    )
    def test_mask_pii_value(self, value: Any, expected: Any) -> None:
        assert _mask_pii_value(value) == expected


class TestPiiColumnKeys:
    def test_expands_qualified_name_to_every_alias_form(self) -> None:
        catalog = Catalog(
            dataset_id="d",
            dimensions={
                "customers.email": DimensionInfo(
                    name="email", label="Email", type="categorical", is_pii=True
                ),
                "orders.channel": DimensionInfo(
                    name="channel", label="Channel", type="categorical", is_pii=False
                ),
            },
        )
        keys = _pii_column_keys(catalog)
        assert keys == {"customers.email", "customers__email", "email"}


class TestPiiMaskGate:
    def _catalog(self, *, pii_dims: dict[str, bool]) -> Any:
        dimensions = {
            name: DimensionInfo(
                name=name.split(".")[-1], label=name, type="categorical", is_pii=is_pii
            )
            for name, is_pii in pii_dims.items()
        }
        return Catalog(dataset_id="d", dimensions=dimensions)

    def test_no_result_set_is_a_no_op(self) -> None:
        state = OmniState(thread_id="t", dataset_id="d")
        result = _run_async(pii_mask_gate(state, config={}))
        assert result.guarded["pii_mask_gate"] == {"status": "no_result_set", "masked": False}

    def test_declared_pii_column_is_redacted_by_qualified_alias(self) -> None:
        state = OmniState(
            thread_id="t",
            dataset_id="ecommerce",
            result_set=[{"customers__email": "jane@example.com", "gross_revenue": 100.0}],
        )
        semantic_provider = Mock()
        semantic_provider.catalog.return_value = self._catalog(pii_dims={"customers.email": True})

        result = _run_async(pii_mask_gate(state, config={"semantic_provider": semantic_provider}))

        assert result.result_set[0]["customers__email"] == "***@***.***"
        assert result.result_set[0]["gross_revenue"] == 100.0
        assert result.guarded["pii_mask_gate"]["masked"] is True
        assert "customers__email" in result.guarded["pii_mask_gate"]["pii_columns_masked"]

    def test_declared_pii_column_with_a_non_pattern_value_is_still_redacted(self) -> None:
        """A declared-PII column (e.g. a customer name) with a value that
        doesn't match any known shape must still be masked -- the catalog's
        declaration is authoritative, not the value-shape heuristic."""
        state = OmniState(
            thread_id="t",
            dataset_id="d",
            result_set=[{"customers__name": "Jane Doe"}],
        )
        semantic_provider = Mock()
        semantic_provider.catalog.return_value = self._catalog(pii_dims={"customers.name": True})

        result = _run_async(pii_mask_gate(state, config={"semantic_provider": semantic_provider}))

        assert result.result_set[0]["customers__name"] == "***"
        assert result.guarded["pii_mask_gate"]["masked"] is True

    def test_value_shape_layer_masks_pii_under_an_arbitrary_alias(self) -> None:
        """sql_agent's model-written SQL can alias a PII column to anything
        (`SELECT email AS contact ...`); with no semantic_provider at all
        (as sql_agent's gate_config may omit it), the value-shape layer
        alone still catches an email-looking value."""
        state = OmniState(
            thread_id="t",
            dataset_id="d",
            result_set=[{"contact": "jane@example.com"}],
        )

        result = _run_async(pii_mask_gate(state, config={}))

        assert result.result_set[0]["contact"] == "***@***.***"
        assert result.guarded["pii_mask_gate"]["masked"] is True

    def test_no_pii_declared_and_no_pii_shaped_values_is_a_clean_pass(self) -> None:
        state = OmniState(
            thread_id="t",
            dataset_id="d",
            result_set=[{"orders__channel": "web", "gross_revenue": 100.0}],
        )
        semantic_provider = Mock()
        semantic_provider.catalog.return_value = self._catalog(pii_dims={"orders.channel": False})

        result = _run_async(pii_mask_gate(state, config={"semantic_provider": semantic_provider}))

        assert result.result_set == [{"orders__channel": "web", "gross_revenue": 100.0}]
        assert result.guarded["pii_mask_gate"] == {"status": "no_pii_found", "masked": False}

    def test_catalog_lookup_failure_falls_back_to_value_shape_layer(self) -> None:
        state = OmniState(
            thread_id="t",
            dataset_id="d",
            result_set=[{"email": "jane@example.com"}],
        )
        semantic_provider = Mock()
        semantic_provider.catalog.side_effect = ValueError("boom")

        result = _run_async(pii_mask_gate(state, config={"semantic_provider": semantic_provider}))

        # The catalog failure is recorded, but the value-shape layer still
        # runs and still masks the obviously-PII-shaped value.
        assert result.result_set[0]["email"] == "***@***.***"
        assert result.guarded["pii_mask_gate"]["masked"] is True

    def test_non_dict_rows_pass_through_untouched(self) -> None:
        state = OmniState(thread_id="t", dataset_id="d", result_set=[{"x": 1}, "not-a-dict"])  # type: ignore[list-item]
        result = _run_async(pii_mask_gate(state, config={}))
        assert result.result_set[1] == "not-a-dict"

    def test_assumption_recorded_once_even_across_multiple_masked_rows(self) -> None:
        state = OmniState(
            thread_id="t",
            dataset_id="d",
            result_set=[{"email": "a@example.com"}, {"email": "b@example.com"}],
        )
        result = _run_async(pii_mask_gate(state, config={}))
        assumption = "Result includes masked PII columns (emails, phone numbers, etc.)"
        assert result.assumptions.count(assumption) == 1

    def test_guarded_dict_initialized_when_none(self) -> None:
        state = OmniState(thread_id="t", dataset_id="d", result_set=None, guarded=None)
        result = _run_async(pii_mask_gate(state, config={}))
        assert isinstance(result.guarded, dict)
        assert "pii_mask_gate" in result.guarded

    def test_existing_guarded_entries_are_preserved(self) -> None:
        state = OmniState(
            thread_id="t",
            dataset_id="d",
            result_set=[{"x": 1}],
            guarded={"other_gate": {"status": "passed"}},
        )
        result = _run_async(pii_mask_gate(state, config={}))
        assert result.guarded["other_gate"]["status"] == "passed"
        assert "pii_mask_gate" in result.guarded
