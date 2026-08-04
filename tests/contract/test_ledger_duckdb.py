"""Conformance tests for DuckDBAnswerLedger against the AnswerLedgerStore port."""

from datetime import UTC, datetime

import pytest

from omniagent.adapters.ledger import DuckDBAnswerLedger
from omniagent.kernel.ports.ledger import LedgerEntry


def _entry(**overrides) -> LedgerEntry:
    defaults = {
        "trace_id": "tr1",
        "thread_id": "th1",
        "dataset_id": "ecommerce",
        "question": "gross revenue",
        "route": "semantic_agent",
        "matched_metric": "gross_revenue",
        "executed_sql": "SELECT 1",
        "confidence": 0.9,
        "error": None,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return LedgerEntry(**defaults)


@pytest.fixture
def ledger():
    with DuckDBAnswerLedger() as store:
        yield store


@pytest.mark.contract
class TestDuckDBAnswerLedgerConformance:
    def test_recorded_entry_is_retrievable_by_thread(self, ledger):
        ledger.record(_entry())

        entries = ledger.for_thread("th1")

        assert len(entries) == 1
        assert entries[0].trace_id == "tr1"
        assert entries[0].matched_metric == "gross_revenue"

    def test_entries_are_ordered_oldest_first(self, ledger):
        ledger.record(_entry(trace_id="tr1", created_at=datetime(2026, 1, 1, tzinfo=UTC)))
        ledger.record(_entry(trace_id="tr2", created_at=datetime(2026, 1, 2, tzinfo=UTC)))

        entries = ledger.for_thread("th1")

        assert [e.trace_id for e in entries] == ["tr1", "tr2"]

    def test_entries_are_isolated_by_thread(self, ledger):
        ledger.record(_entry(trace_id="tr1", thread_id="th1"))
        ledger.record(_entry(trace_id="tr2", thread_id="th2"))

        assert [e.trace_id for e in ledger.for_thread("th1")] == ["tr1"]
        assert [e.trace_id for e in ledger.for_thread("th2")] == ["tr2"]

    def test_unknown_thread_returns_empty_list(self, ledger):
        assert ledger.for_thread("nonexistent") == []

    def test_error_and_abstention_entries_record_correctly(self, ledger):
        ledger.record(
            _entry(
                trace_id="tr-err",
                route=None,
                matched_metric=None,
                executed_sql=None,
                confidence=None,
                error="no matching metric",
            )
        )

        entry = ledger.for_thread("th1")[0]
        assert entry.error == "no matching metric"
        assert entry.matched_metric is None
        assert entry.confidence is None
