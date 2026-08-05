"""Pytest configuration and shared fixtures for omniagent tests."""

import os
import time

import duckdb
import pytest

from omniagent.adapters.engine.duckdb import DuckDBEngine

# Must run before any fixture constructs a FastEmbedProvider (the verified-query
# fast path's embedder). huggingface_hub's Xet-accelerated download backend calls
# a now-deprecated hf_xet function on every first-time model download; this
# project's own filterwarnings turns that third-party DeprecationWarning into a
# hard error, which only ever fires on a genuinely cold cache (a fresh clone, or
# a CI runner, never a machine that already has the model cached from a previous
# run). Disabling Xet falls back to the plain HTTP download path, which does not
# hit the deprecated call.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def pytest_configure(config):
    """Pre-warm the fast path's embedding model once, in the controller
    process, before pytest-xdist spawns worker processes.

    `hasattr(config, "workerinput")` is xdist's own idiom for "this is a
    worker, not the controller" -- it's only set on workers. Without this,
    every worker that happens to run a fastembed-touching test for the
    first time races to download and load the same model into
    `/tmp/fastembed_cache` concurrently; on a memory-constrained runner
    this has been observed to crash the worker process outright (not a
    clean Python exception, "node down: not properly terminated"), not
    just log a benign download-collision warning. Warming it once here
    means every worker's own FastEmbedProvider() construction just loads
    an already-complete file from disk instead of racing a download.
    """
    if hasattr(config, "workerinput"):
        return

    from omniagent.adapters.embeddings import FastEmbedProvider

    # A handful of retries: on a shared CI runner, the anonymous Hugging
    # Face Hub download this triggers can hit a transient rate limit or
    # network blip that a developer machine's first run essentially never
    # sees. Retrying here is cheap (a failed attempt fails fast) and turns
    # a one-off network hiccup into a warm cache instead of every worker
    # independently hitting the same failure later with no retry of its own.
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            FastEmbedProvider()
            return
        except Exception as exc:  # noqa: BLE001 - retried below, not swallowed silently
            last_exc = exc
            if attempt < 2:
                time.sleep(2**attempt)

    # If every attempt failed (offline, extra not installed, a genuinely
    # down endpoint), let whichever worker actually needs the model surface
    # the real error itself rather than masking it here -- just note that
    # the warm-up itself didn't happen.
    print(f"fastembed pre-warm skipped after 3 attempts: {last_exc}")  # noqa: T201


@pytest.fixture
def ecommerce_warehouse(tmp_path):
    """A tiny DuckDB warehouse matching packs/ecommerce/semantic.yml's tables.

    Shared across contract, component, and integration tests. Values are
    chosen so every metric's expected result can be computed by hand and
    asserted exactly, rather than trusting the code under test to grade
    itself.

    Customers: C1 (signup 2026-01-15), C2 (signup 2026-02-01, Q1), C3 (signup
    2026-04-01, Q2 boundary — excluded from a Q1 time_range by the exclusive
    upper bound).

    Orders: O1/O2 (C1, completed, web), O3 (C2, cancelled — excluded from
    every metric filtered on order_status=completed), O4 (C3, completed,
    mobile_app). Completed gross_revenue = 100 + 50 + 75 = 225.
    order_count = 3.

    Returns: R1 (approved, on O1, refund 20), R2 (pending, on O2 —
    excluded). refunds = 20. net_revenue = 225 - 20 = 205. return_count = 1.
    return_rate = 1/3.

    Order items: I1 (O1, qty 2), I2 (O2, qty 1), I3 (O3, qty 5 — excluded,
    parent order cancelled), I4 (O4, qty 3). units_sold = 2 + 1 + 3 = 6.
    """
    db_path = tmp_path / "warehouse.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE ecommerce_customers (
            customer_id VARCHAR, country VARCHAR, region VARCHAR,
            customer_segment VARCHAR, marketing_channel VARCHAR,
            signup_date DATE, email VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO ecommerce_customers VALUES
        ('C1', 'US', 'West', 'consumer', 'organic', '2026-01-15', 'c1@example.com'),
        ('C2', 'US', 'East', 'business', 'paid_search', '2026-02-01', 'c2@example.com'),
        ('C3', 'UK', 'London', 'consumer', 'referral', '2026-04-01', 'c3@example.com')
    """)
    conn.execute("""
        CREATE TABLE ecommerce_orders (
            order_id VARCHAR, customer_id VARCHAR, order_date DATE,
            order_status VARCHAR, channel VARCHAR, payment_method VARCHAR,
            shipping_country VARCHAR, discount_code VARCHAR, order_total DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO ecommerce_orders VALUES
        ('O1', 'C1', '2026-04-15', 'completed', 'web', 'card', 'US', NULL, 100.0),
        ('O2', 'C1', '2026-05-10', 'completed', 'web', 'card', 'US', NULL, 50.0),
        ('O3', 'C2', '2026-01-25', 'cancelled', 'web', 'card', 'US', NULL, 200.0),
        ('O4', 'C3', '2026-04-05', 'completed', 'mobile_app', 'card', 'UK', NULL, 75.0)
    """)
    conn.execute("""
        CREATE TABLE ecommerce_order_items (
            order_item_id VARCHAR, order_id VARCHAR, product_id VARCHAR,
            quantity INTEGER, line_total DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO ecommerce_order_items VALUES
        ('I1', 'O1', 'P1', 2, 100.0),
        ('I2', 'O2', 'P1', 1, 50.0),
        ('I3', 'O3', 'P2', 5, 200.0),
        ('I4', 'O4', 'P2', 3, 75.0)
    """)
    conn.execute("""
        CREATE TABLE ecommerce_products (
            product_id VARCHAR, category VARCHAR, subcategory VARCHAR, brand VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO ecommerce_products VALUES
        ('P1', 'apparel', 'shirts', 'brand_a'),
        ('P2', 'apparel', 'pants', 'brand_b')
    """)
    conn.execute("""
        CREATE TABLE ecommerce_returns (
            return_id VARCHAR, order_id VARCHAR, return_reason VARCHAR,
            return_status VARCHAR, return_date DATE, refund_amount DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO ecommerce_returns VALUES
        ('R1', 'O1', 'defective', 'approved', '2026-04-25', 20.0),
        ('R2', 'O2', 'wrong_size', 'pending', '2026-05-15', 10.0)
    """)
    conn.close()

    engine = DuckDBEngine(db_path, read_only=True)
    yield engine
    engine.close()


@pytest.fixture
def saas_warehouse(tmp_path):
    """A tiny DuckDB warehouse matching packs/saas/semantic.yml's tables.

    Unlike ecommerce_warehouse, values here are not hand-verified against
    every metric (no test currently asserts exact SaaS numbers) -- this
    fixture exists so real join paths across all five SaaS models can
    actually be executed, which is what caught a real join_type/
    join_condition bug in native_yaml.py's _join_path that only manifested
    at execution time (see test_semantic_native_yaml.py's regression test).
    """
    db_path = tmp_path / "saas_warehouse.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE saas_accounts (
            account_id VARCHAR, industry VARCHAR, company_size VARCHAR,
            country VARCHAR, signup_date DATE, is_active BOOLEAN,
            churn_date DATE, account_owner_email VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO saas_accounts VALUES
        ('A1', 'Healthcare', 'mid_market', 'US', '2025-01-10', true, NULL, 'owner1@example.com'),
        ('A2', 'Financial Services', 'enterprise', 'UK', '2025-03-01', true, NULL, 'owner2@example.com')
    """)
    conn.execute("""
        CREATE TABLE saas_subscriptions (
            subscription_id VARCHAR, account_id VARCHAR, plan_name VARCHAR,
            billing_cycle VARCHAR, status VARCHAR, start_date DATE,
            end_date DATE, mrr_amount DOUBLE, seats INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO saas_subscriptions VALUES
        ('S1', 'A1', 'pro', 'monthly', 'active', '2025-01-15', NULL, 500.0, 10),
        ('S2', 'A2', 'enterprise', 'annual', 'active', '2025-03-05', NULL, 2000.0, 50)
    """)
    conn.execute("""
        CREATE TABLE saas_invoices (
            invoice_id VARCHAR, subscription_id VARCHAR, invoice_date DATE,
            status VARCHAR, payment_method VARCHAR, amount_due DOUBLE, amount_paid DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO saas_invoices VALUES
        ('I1', 'S1', '2025-02-01', 'paid', 'card', 500.0, 500.0),
        ('I2', 'S2', '2025-04-01', 'paid', 'wire', 2000.0, 2000.0)
    """)
    conn.execute("""
        CREATE TABLE saas_usage_events (
            event_id VARCHAR, subscription_id VARCHAR, account_id VARCHAR,
            event_timestamp TIMESTAMP, event_type VARCHAR, event_count INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO saas_usage_events VALUES
        ('E1', 'S1', 'A1', '2025-02-10 10:00:00', 'login', 5),
        ('E2', 'S2', 'A2', '2025-04-10 10:00:00', 'export', 2)
    """)
    conn.execute("""
        CREATE TABLE saas_support_tickets (
            ticket_id VARCHAR, account_id VARCHAR, created_at TIMESTAMP,
            category VARCHAR, priority VARCHAR, status VARCHAR,
            assigned_agent_email VARCHAR, satisfaction_score DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO saas_support_tickets VALUES
        ('T1', 'A1', '2025-02-15 09:00:00', 'billing', 'low', 'closed', 'agent1@example.com', 4.5),
        ('T2', 'A2', '2025-04-15 09:00:00', 'bug', 'high', 'open', 'agent2@example.com', 3.0)
    """)
    conn.close()

    engine = DuckDBEngine(db_path, read_only=True)
    yield engine
    engine.close()
