"""Pytest configuration and shared fixtures for omniagent tests."""

import duckdb
import pytest

from omniagent.adapters.engine.duckdb import DuckDBEngine


def pytest_configure(config):
    """Configure pytest with additional markers."""
    # Markers are already defined in pyproject.toml, but we can add runtime setup here
    pass


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
