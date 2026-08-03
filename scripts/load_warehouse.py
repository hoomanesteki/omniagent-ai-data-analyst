#!/usr/bin/env python3
# ruff: noqa: T201
"""Load the generated sample CSVs into a DuckDB warehouse file.

Run after ``generate_samples.py``. The warehouse is a build artifact, not a
source of truth: it is gitignored and rebuilt from the CSVs, which are
themselves rebuilt deterministically from the seed.

    python scripts/load_warehouse.py
    python scripts/load_warehouse.py --samples data/samples --out data/warehouse/omniagent.duckdb
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

DEFAULT_SAMPLES = Path("data/samples")
DEFAULT_WAREHOUSE = Path("data/warehouse/omniagent.duckdb")

# Columns DuckDB's sniffer reads as VARCHAR because the sample is sparse, but
# which the semantic layer compares against real dates.
TIMESTAMP_COLUMNS = {
    "ecommerce_orders": ["order_date"],
    "saas_support_tickets": ["created_at", "resolved_at"],
    "saas_usage_events": ["event_timestamp"],
}
DATE_COLUMNS = {
    "ecommerce_customers": ["signup_date"],
    "ecommerce_products": ["launch_date"],
    "ecommerce_returns": ["return_date"],
    "saas_accounts": ["signup_date", "churn_date"],
    "saas_subscriptions": ["start_date", "end_date"],
    "saas_invoices": ["invoice_date", "due_date"],
}


def load(samples_dir: Path, warehouse_path: Path) -> int:
    csv_paths = sorted(samples_dir.glob("*.csv"))
    if not csv_paths:
        print(f"No CSVs in {samples_dir}. Run scripts/generate_samples.py first.", file=sys.stderr)
        return 1

    warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    if warehouse_path.exists():
        warehouse_path.unlink()

    conn = duckdb.connect(str(warehouse_path))
    try:
        for csv_path in csv_paths:
            table = csv_path.stem
            overrides = {
                **dict.fromkeys(TIMESTAMP_COLUMNS.get(table, []), "TIMESTAMP"),
                **dict.fromkeys(DATE_COLUMNS.get(table, []), "DATE"),
            }
            types_clause = ""
            if overrides:
                pairs = ", ".join(f"'{col}': '{sql_type}'" for col, sql_type in overrides.items())
                types_clause = f", types = {{{pairs}}}"

            conn.execute(
                f"CREATE OR REPLACE TABLE {table} AS "  # noqa: S608 - table name from filename
                f"SELECT * FROM read_csv(?, header = true, sample_size = -1{types_clause})",
                [str(csv_path)],
            )
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
            print(f"  loaded {table:28} {count:>7,} rows")
    finally:
        conn.close()

    print(f"\nWarehouse written to {warehouse_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--out", type=Path, default=DEFAULT_WAREHOUSE)
    args = parser.parse_args()
    return load(args.samples, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
