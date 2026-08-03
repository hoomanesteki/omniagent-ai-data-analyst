"""Conformance tests for NativeYamlProvider against the real ecommerce pack.

Uses the committed packs/ecommerce/semantic.yml (not a synthetic pack) against
the hand-computed fixture warehouse in conftest.py, so every assertion checks
an exact expected number rather than just "it didn't crash."
"""

import subprocess
from datetime import date

import pytest

from omniagent.adapters.semantic.native_yaml import NativeYamlProvider
from omniagent.kernel.ports.semantic import SemanticIssue, SemanticQuery
from omniagent.kernel.ports.time import TimeRange


@pytest.fixture
def provider():
    return NativeYamlProvider("packs")


@pytest.mark.contract
class TestNativeYamlProviderConformance:
    def test_catalog_lists_known_metrics_and_dimensions(self, provider):
        catalog = provider.catalog("ecommerce")
        assert "gross_revenue" in catalog.metrics
        assert "net_revenue" in catalog.metrics
        assert "orders.order_date" in catalog.dimensions

    def test_schema_version_is_stable_and_content_derived(self, provider):
        v1 = provider.schema_version("ecommerce")
        v2 = provider.schema_version("ecommerce")
        assert v1 == v2
        assert v1 != provider.schema_version("saas")

    def test_validate_unknown_metric_reports_known_metrics(self, provider):
        issues = provider.validate("ecommerce", SemanticQuery(metrics=("not_a_metric",)))
        assert len(issues) == 1
        assert "Unknown metric" in str(issues[0])
        assert "gross_revenue" in str(issues[0])

    def test_validate_negative_limit_rejected(self, provider):
        issues = provider.validate("ecommerce", SemanticQuery(metrics=("order_count",), limit=0))
        assert any("Limit must be positive" in str(i) for i in issues)

    @pytest.mark.parametrize(
        "metric,expected",
        [
            ("gross_revenue", 225.0),
            ("refunds", 20.0),
            ("net_revenue", 205.0),
            ("order_count", 3),
            ("units_sold", 6),
            ("average_order_value", 75.0),
            ("customer_count", 3),
            ("return_count", 1),
        ],
    )
    def test_metric_compiles_and_computes_exact_value(
        self, provider, ecommerce_warehouse, metric, expected
    ):
        q = SemanticQuery(metrics=(metric,), limit=10)
        assert provider.validate("ecommerce", q) == []
        compiled = provider.compile("ecommerce", q)
        result = ecommerce_warehouse.execute(
            compiled.sql, params=compiled.provenance["params"], row_cap=10
        )
        assert result.batches == [(expected,)]

    def test_return_rate_ratio(self, provider, ecommerce_warehouse):
        q = SemanticQuery(metrics=("return_rate",), limit=10)
        compiled = provider.compile("ecommerce", q)
        result = ecommerce_warehouse.execute(
            compiled.sql, params=compiled.provenance["params"], row_cap=10
        )
        (value,) = result.batches[0]
        assert value == pytest.approx(1 / 3)

    def test_group_by_dimension(self, provider, ecommerce_warehouse):
        q = SemanticQuery(metrics=("gross_revenue",), group_by=("orders.channel",), limit=10)
        compiled = provider.compile("ecommerce", q)
        result = ecommerce_warehouse.execute(
            compiled.sql, params=compiled.provenance["params"], row_cap=10
        )
        by_channel = dict(result.batches)
        assert by_channel == {"web": 150.0, "mobile_app": 75.0}

    def test_customer_count_unfiltered_does_not_require_orders_join(
        self, provider, ecommerce_warehouse
    ):
        """Regression: a query with no time_range must not pull in the metric's
        default_time_dimension's model — doing so previously forced an
        unrelated, fan-out-unsafe join (customers -> orders) purely to
        support time filtering nothing had asked for."""
        q = SemanticQuery(metrics=("customer_count",), limit=10)
        assert provider.validate("ecommerce", q) == []
        compiled = provider.compile("ecommerce", q)
        assert "ecommerce_orders" not in compiled.sql
        result = ecommerce_warehouse.execute(
            compiled.sql, params=compiled.provenance["params"], row_cap=10
        )
        assert result.batches == [(3,)]

    def test_customer_count_time_filtered_by_signup_date(self, provider, ecommerce_warehouse):
        """With a time_range, the default_time_dimension (customers.signup_date)
        is applied and correctly excludes C3, whose signup lands exactly on the
        exclusive upper bound."""
        q1_range = TimeRange(start=date(2026, 1, 1), end=date(2026, 4, 1), grain="quarter")
        q = SemanticQuery(metrics=("customer_count",), time_range=q1_range, limit=10)
        assert provider.validate("ecommerce", q) == []
        compiled = provider.compile("ecommerce", q)
        result = ecommerce_warehouse.execute(
            compiled.sql, params=compiled.provenance["params"], row_cap=10
        )
        assert result.batches == [(2,)]

    def test_compile_raises_semantic_issue_on_unknown_metric(self, provider):
        with pytest.raises(SemanticIssue):
            provider.compile("ecommerce", SemanticQuery(metrics=("not_a_metric",)))

    def test_capabilities_declared(self, provider):
        caps = provider.capabilities()
        assert caps.ratio is True
        assert caps.derived is True

    def test_compile_spawns_zero_subprocesses(self, provider, monkeypatch):
        """The whole point of an in-process semantic provider is no subprocess
        tax per turn — a real dbt/MetricFlow provider pays 6-16s per call that
        this design exists to avoid."""
        calls = []
        original_popen = subprocess.Popen

        def spy_popen(*args, **kwargs):
            calls.append((args, kwargs))
            return original_popen(*args, **kwargs)

        monkeypatch.setattr(subprocess, "Popen", spy_popen)

        q = SemanticQuery(metrics=("net_revenue",), group_by=("orders.channel",), limit=10)
        provider.validate("ecommerce", q)
        provider.compile("ecommerce", q)

        assert calls == []


@pytest.mark.contract
class TestSaasPackLoadsAndCompiles:
    """Regression: collected_revenue's filter used to reference the raw
    column name (invoices.status) instead of the declared dimension
    (invoices.invoice_status). That doesn't just break that one metric — a
    bad reference anywhere in the pack fails _check_references() during
    _load(), which blocks catalog()/compile() for every metric in the pack.
    So the real regression check is that the whole pack loads and every
    metric compiles cleanly, not just that one metric's SQL looks right."""

    def test_catalog_loads_without_error(self, provider):
        catalog = provider.catalog("saas")
        assert "collected_revenue" in catalog.metrics
        assert len(catalog.metrics) >= 10

    def test_every_metric_validates_and_compiles(self, provider):
        catalog = provider.catalog("saas")
        for metric_name in catalog.metrics:
            q = SemanticQuery(metrics=(metric_name,), limit=5)
            issues = provider.validate("saas", q)
            assert issues == [], f"{metric_name}: {issues}"
            compiled = provider.compile("saas", q)
            assert compiled.sql

    def test_collected_revenue_filters_on_paid_status(self, provider):
        compiled = provider.compile("saas", SemanticQuery(metrics=("collected_revenue",), limit=5))
        assert "invoices.status" in compiled.sql
        assert compiled.provenance["params"] == ["paid"]
