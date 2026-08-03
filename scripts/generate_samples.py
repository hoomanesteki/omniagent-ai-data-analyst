#!/usr/bin/env python3
# ruff: noqa: T201, S311
"""Deterministic seeded sample-data generator for OmniAgent 2.0.

Generates two synthetic, referentially-intact CSV datasets used to build and
test the e-commerce and SaaS semantic-layer packs:

    e-commerce  customers, products, orders, order_items, returns
    SaaS        accounts, subscriptions, usage_events, invoices,
                support_tickets

Spec note
---------
This script was written against a request to follow "12_SAMPLE_DATA.md
S12.2/12.3". No such file exists anywhere in this repository (checked
docs/, packs/, and the full tree) at the time of writing -- only indirect
references to `generate_samples.py --seed 1337` in ARCHITECTURE_OVERVIEW.md
and BUILD_STATUS.md, with no schema detail. Absent that spec, the table
shapes, seasonality curves, null-injection strategy, and row volumes below
are original, documented design decisions sized to satisfy the *behavior*
requested (realistic seasonality, 1-3% nulls on data-quality-sensitive
columns, full referential integrity, deterministic seeded output). If
`docs/12_SAMPLE_DATA.md` is added later with a different schema, reconcile
against it -- this docstring is the paper trail for what to check.

Determinism
-----------
- Every random draw comes from `random.Random(...)` streams seeded from a
  string key derived from `--seed`, never from wall-clock time or the
  process's hash seed. Same `--seed` + `--ref-date` => byte-identical CSVs,
  every run, on the same Python version (the repo pins 3.12 via
  .python-version).
- `--ref-date` is the generator's notion of "today"; all history is
  generated strictly at or before it (no dates in the future).

Nulls
-----
1-3% null rates (drawn once per column, per run, from `random.uniform(0.01,
0.03)`, then applied per-row) are injected into columns that would normally
always be populated in a clean system of record: emails, regions, marketing
channel, payment method, weight, return reason, CSM owner, assigned agent.
A handful of columns are legitimately sparse by *business* logic rather than
by data-quality noise (discount_code, satisfaction_score, resolved_at) --
those use their own realistic sparsity rates and are called out inline; they
are not part of the 1-3% budget.

Usage
-----
    python scripts/generate_samples.py --seed 1337
    python scripts/generate_samples.py --seed 1337 --ref-date 2026-07-31 \\
        --out-dir data/samples
"""

from __future__ import annotations

import argparse
import bisect
import csv
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Defaults / constants
# ---------------------------------------------------------------------------

DEFAULT_SEED = 1337
DEFAULT_REF_DATE = date(2026, 7, 31)
DEFAULT_OUT_DIR = Path("data/samples")

N_CUSTOMERS = 1_000
N_PRODUCTS = 150
N_ORDERS = 6_000
N_ACCOUNTS = 350

ECOMMERCE_HISTORY_DAYS = 730  # 2 years
SAAS_HISTORY_DAYS = 1_095  # 3 years

Row = dict[str, Any]
TableSpec = dict[str, tuple[list[str], list[Row]]]

# ---------------------------------------------------------------------------
# Name / vocabulary pools (kept in stdlib, no Faker dependency)
# ---------------------------------------------------------------------------

FIRST_NAMES = [
    "James",
    "Mary",
    "John",
    "Patricia",
    "Robert",
    "Jennifer",
    "Michael",
    "Linda",
    "William",
    "Elizabeth",
    "David",
    "Barbara",
    "Richard",
    "Susan",
    "Joseph",
    "Jessica",
    "Thomas",
    "Sarah",
    "Charles",
    "Karen",
    "Christopher",
    "Nancy",
    "Daniel",
    "Lisa",
    "Matthew",
    "Betty",
    "Anthony",
    "Margaret",
    "Mark",
    "Sandra",
    "Donald",
    "Ashley",
    "Steven",
    "Kimberly",
    "Andrew",
    "Emily",
    "Joshua",
    "Donna",
    "Kenneth",
    "Michelle",
    "Kevin",
    "Carol",
    "Brian",
    "Amanda",
    "George",
    "Melissa",
    "Priya",
    "Wei",
    "Fatima",
    "Liam",
    "Noah",
    "Olivia",
    "Emma",
    "Sofia",
    "Mateo",
    "Yuki",
    "Chen",
    "Aisha",
    "Omar",
]
LAST_NAMES = [
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Rodriguez",
    "Martinez",
    "Hernandez",
    "Lopez",
    "Gonzalez",
    "Wilson",
    "Anderson",
    "Thomas",
    "Taylor",
    "Moore",
    "Jackson",
    "Martin",
    "Lee",
    "Perez",
    "Thompson",
    "White",
    "Harris",
    "Sanchez",
    "Clark",
    "Ramirez",
    "Lewis",
    "Robinson",
    "Walker",
    "Young",
    "Allen",
    "King",
    "Wright",
    "Scott",
    "Torres",
    "Nguyen",
    "Hill",
    "Flores",
    "Green",
    "Adams",
    "Nelson",
    "Baker",
    "Hall",
    "Rivera",
    "Campbell",
    "Mitchell",
]

COMPANY_ADJ = [
    "Bright",
    "Nimbus",
    "Clearwater",
    "Northwind",
    "Silverline",
    "Bluepeak",
    "Ironwood",
    "Solstice",
    "Vertex",
    "Cobalt",
    "Amber",
    "Crescent",
    "Lighthouse",
    "Meridian",
    "Quartz",
    "Redwood",
    "Sable",
    "Timberline",
    "Willowbrook",
    "Fernwood",
]
COMPANY_NOUN = [
    "Analytics",
    "Systems",
    "Labs",
    "Works",
    "Dynamics",
    "Networks",
    "Solutions",
    "Digital",
    "Cloud",
    "Data",
    "Ventures",
    "Logistics",
    "Health",
    "Media",
    "Finance",
    "Retail",
    "Studio",
    "Technologies",
]
COMPANY_SUFFIX = ["Inc.", "LLC", "Co.", "Corp.", "Ltd."]

BRANDS = [
    "Zenlyte",
    "Kestrel",
    "Marrow & Co",
    "Vantage Point",
    "Northfield",
    "Halcyon",
    "Ridgeline",
    "Wrenfield",
    "Solace",
    "Fernbrook",
    "Ampfield",
    "Brightside",
    "Ironclad",
    "Meadowlane",
    "Driftwood",
    "Anchorpoint",
    "Highgrove",
    "Lumen",
    "Everline",
    "Palisade",
]
PRODUCT_DESCRIPTORS = [
    "Premium",
    "Classic",
    "Everyday",
    "Pro",
    "Essential",
    "Deluxe",
    "Compact",
    "Ultra",
    "Signature",
    "Original",
]

# ---------------------------------------------------------------------------
# E-commerce domain vocab
# ---------------------------------------------------------------------------

COUNTRIES = ["US", "CA", "GB", "DE", "FR", "AU", "NL", "SE", "IE", "ES"]
COUNTRY_WEIGHTS = [40, 12, 10, 8, 6, 6, 4, 4, 5, 5]
US_STATES = [
    "CA",
    "TX",
    "NY",
    "FL",
    "IL",
    "WA",
    "MA",
    "CO",
    "GA",
    "NC",
    "VA",
    "OH",
    "PA",
    "AZ",
    "OR",
]
REGIONS_BY_COUNTRY = {
    "CA": ["Ontario", "Quebec", "British Columbia", "Alberta", "Manitoba"],
    "GB": ["England", "Scotland", "Wales", "Northern Ireland"],
    "DE": ["Bavaria", "Berlin", "Hesse", "North Rhine-Westphalia", "Saxony"],
    "FR": ["Ile-de-France", "Provence-Alpes-Cote d'Azur", "Occitanie", "Nouvelle-Aquitaine"],
    "AU": ["New South Wales", "Victoria", "Queensland", "Western Australia"],
    "NL": ["North Holland", "South Holland", "Utrecht"],
    "SE": ["Stockholm County", "Vaestra Goetaland", "Skane"],
    "IE": ["Leinster", "Munster", "Connacht"],
    "ES": ["Madrid", "Catalonia", "Andalusia", "Valencia"],
}
CUSTOMER_SEGMENTS = ["consumer", "small_business", "enterprise"]
CUSTOMER_SEGMENT_WEIGHTS = [78, 17, 5]
MARKETING_CHANNELS = [
    "organic_search",
    "paid_search",
    "paid_social",
    "email",
    "referral",
    "affiliate",
    "direct",
]
MARKETING_CHANNEL_WEIGHTS = [22, 20, 16, 13, 12, 10, 7]

CATEGORY_SUBCATS = {
    "Electronics": [
        "Headphones",
        "Smartphone Accessories",
        "Laptop Accessories",
        "Cameras",
        "Smart Home",
    ],
    "Apparel": ["Men's Wear", "Women's Wear", "Kids Wear", "Footwear", "Outerwear"],
    "Home & Kitchen": ["Cookware", "Small Appliances", "Furniture", "Home Decor", "Bedding"],
    "Beauty": ["Skincare", "Haircare", "Makeup", "Fragrance"],
    "Sports & Outdoors": ["Fitness Equipment", "Camping Gear", "Cycling", "Team Sports"],
    "Books": ["Fiction", "Non-Fiction", "Children's Books", "Comics & Graphic Novels"],
    "Toys & Games": ["Action Figures", "Board Games", "Educational Toys", "Outdoor Play"],
    "Grocery": ["Snacks", "Beverages", "Pantry Staples", "Fresh Produce"],
}
CATEGORY_WEIGHTS = [18, 16, 14, 12, 12, 8, 10, 10]
COST_RANGE_BY_CATEGORY = {
    "Electronics": (20, 300),
    "Apparel": (5, 60),
    "Home & Kitchen": (8, 150),
    "Beauty": (3, 40),
    "Sports & Outdoors": (10, 200),
    "Books": (3, 20),
    "Toys & Games": (4, 60),
    "Grocery": (1, 15),
}

ORDER_MONTH_SEASONALITY = {
    1: 0.75,
    2: 0.80,
    3: 0.90,
    4: 0.95,
    5: 1.00,
    6: 1.00,
    7: 0.95,
    8: 1.05,
    9: 1.00,
    10: 1.15,
    11: 1.65,
    12: 1.90,
}
ORDER_WEEKDAY_SEASONALITY = {0: 0.95, 1: 0.95, 2: 1.00, 3: 1.05, 4: 1.15, 5: 1.20, 6: 1.05}
ORDER_HOUR_WEIGHTS = [
    1,
    1,
    1,
    1,
    1,
    2,
    3,
    5,
    8,
    10,
    12,
    14,
    15,
    14,
    13,
    13,
    14,
    16,
    18,
    17,
    14,
    10,
    5,
    2,
]

SIGNUP_WEEKDAY_SEASONALITY = {0: 1.05, 1: 1.05, 2: 1.05, 3: 1.05, 4: 1.0, 5: 0.85, 6: 0.85}
FLAT_MONTH = dict.fromkeys(range(1, 13), 1.0)
FLAT_WEEKDAY = dict.fromkeys(range(7), 1.0)

CHANNELS_ORD = ["web", "mobile_app", "marketplace", "in_store"]
CHANNEL_WEIGHTS_ORD = [50, 32, 13, 5]
PAYMENT_METHODS = ["credit_card", "paypal", "gift_card", "bank_transfer", "buy_now_pay_later"]
PAYMENT_WEIGHTS = [55, 22, 8, 7, 8]
RETURN_REASONS = [
    "defective",
    "wrong_item_shipped",
    "not_as_described",
    "changed_mind",
    "damaged_in_shipping",
    "late_delivery",
]
RETURN_REASON_WEIGHTS = [22, 15, 18, 25, 12, 8]
RETURN_RATE = 0.07  # share of eligible (completed-order) line items that get returned

# ---------------------------------------------------------------------------
# SaaS domain vocab
# ---------------------------------------------------------------------------

INDUSTRIES = [
    "Technology",
    "Financial Services",
    "Healthcare",
    "Retail & E-commerce",
    "Education",
    "Manufacturing",
    "Media & Entertainment",
    "Professional Services",
    "Other",
]
INDUSTRY_WEIGHTS = [24, 14, 10, 12, 8, 8, 7, 10, 7]
COMPANY_SIZES = ["startup", "smb", "mid_market", "enterprise"]
COMPANY_SIZE_WEIGHTS = [32, 36, 22, 10]
SAAS_COUNTRIES = ["US", "GB", "CA", "DE", "AU", "FR", "IN", "NL", "SG", "IE"]
SAAS_COUNTRY_WEIGHTS = [45, 12, 10, 7, 6, 5, 6, 4, 3, 2]

SAAS_MONTH_SEASONALITY = {
    1: 1.05,
    2: 1.0,
    3: 1.05,
    4: 1.0,
    5: 1.0,
    6: 0.95,
    7: 0.85,
    8: 0.85,
    9: 1.05,
    10: 1.1,
    11: 1.0,
    12: 0.75,
}
SAAS_WEEKDAY_SEASONALITY = {0: 1.15, 1: 1.20, 2: 1.20, 3: 1.15, 4: 1.0, 5: 0.15, 6: 0.1}
SAAS_HOUR_WEIGHTS = [
    1,
    1,
    1,
    1,
    1,
    1,
    2,
    4,
    10,
    16,
    18,
    18,
    14,
    16,
    18,
    17,
    14,
    8,
    4,
    2,
    1,
    1,
    1,
    1,
]

PLAN_NAMES = ["Starter", "Growth", "Professional", "Enterprise"]
PLAN_SEATS_RANGE = {
    "Starter": (1, 5),
    "Growth": (5, 20),
    "Professional": (20, 100),
    "Enterprise": (100, 400),
}
PLAN_PRICE_PER_SEAT = {
    "Starter": (15, 25),
    "Growth": (25, 40),
    "Professional": (35, 55),
    "Enterprise": (45, 70),
}
PLAN_BY_SIZE_WEIGHTS = {
    "startup": [55, 30, 12, 3],
    "smb": [30, 42, 22, 6],
    "mid_market": [10, 25, 45, 20],
    "enterprise": [3, 10, 32, 55],
}
ANNUAL_DISCOUNT = 0.15
PLAN_ACTIVITY_FACTOR = {"Starter": 0.6, "Growth": 1.0, "Professional": 1.6, "Enterprise": 2.4}

PAYMENT_METHODS_SAAS = ["credit_card", "ach", "wire_transfer", "invoice_net_terms"]
PAYMENT_WEIGHTS_SAAS = [45, 28, 15, 12]

EVENT_TYPES = [
    "login",
    "api_call",
    "report_generated",
    "data_export",
    "dashboard_view",
    "feature_used",
]
EVENT_WEIGHTS = [28, 26, 10, 8, 20, 8]

TICKET_CATEGORIES = ["technical", "billing", "feature_request", "onboarding", "bug"]
TICKET_CATEGORY_WEIGHTS = [32, 20, 20, 15, 13]
TICKET_PRIORITIES = ["low", "medium", "high", "urgent"]
TICKET_PRIORITY_WEIGHTS = [38, 37, 18, 7]
SIZE_TICKET_FACTOR = {"startup": 0.6, "smb": 1.0, "mid_market": 1.8, "enterprise": 3.0}

# ---------------------------------------------------------------------------
# CSV column order (explicit, so column order never depends on dict/hash
# ordering; internal helper keys prefixed "_" are dropped by DictWriter via
# extrasaction="ignore")
# ---------------------------------------------------------------------------

CUSTOMERS_FIELDS = [
    "customer_id",
    "first_name",
    "last_name",
    "email",
    "signup_date",
    "country",
    "region",
    "customer_segment",
    "marketing_channel",
]
PRODUCTS_FIELDS = [
    "product_id",
    "product_name",
    "category",
    "subcategory",
    "brand",
    "unit_cost",
    "unit_price",
    "launch_date",
    "is_active",
    "weight_kg",
]
ORDERS_FIELDS = [
    "order_id",
    "customer_id",
    "order_date",
    "order_status",
    "channel",
    "payment_method",
    "shipping_country",
    "discount_code",
    "order_total",
    "currency",
]
ORDER_ITEMS_FIELDS = [
    "order_item_id",
    "order_id",
    "product_id",
    "quantity",
    "unit_price",
    "discount_pct",
    "line_total",
]
RETURNS_FIELDS = [
    "return_id",
    "order_id",
    "order_item_id",
    "return_date",
    "return_reason",
    "return_status",
    "refund_amount",
]

ACCOUNTS_FIELDS = [
    "account_id",
    "account_name",
    "industry",
    "company_size",
    "country",
    "signup_date",
    "account_owner_email",
    "is_active",
    "churn_date",
]
SUBSCRIPTIONS_FIELDS = [
    "subscription_id",
    "account_id",
    "plan_name",
    "billing_cycle",
    "seats",
    "mrr_amount",
    "discount_pct",
    "start_date",
    "end_date",
    "status",
]
INVOICES_FIELDS = [
    "invoice_id",
    "account_id",
    "subscription_id",
    "invoice_date",
    "due_date",
    "amount_due",
    "amount_paid",
    "status",
    "payment_method",
]
USAGE_EVENTS_FIELDS = [
    "event_id",
    "account_id",
    "subscription_id",
    "event_timestamp",
    "event_type",
    "event_count",
    "duration_seconds",
]
SUPPORT_TICKETS_FIELDS = [
    "ticket_id",
    "account_id",
    "created_at",
    "category",
    "priority",
    "status",
    "resolved_at",
    "satisfaction_score",
    "assigned_agent_email",
]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def rng_for(seed: int, stream: str) -> random.Random:
    """Independent, deterministic RNG stream per table/generator.

    random.Random's string seeding is stable across processes and Python
    versions (it does not depend on PYTHONHASHSEED), so this gives fully
    reproducible, decoupled streams per table for the same --seed.
    """
    return random.Random(f"{seed}::{stream}")


def weighted_choice(rng: random.Random, items: list[Any], weights: list[float]) -> Any:
    return rng.choices(items, weights=weights, k=1)[0]


def null_rate(rng: random.Random) -> float:
    """1-3% null rate, drawn once per column per run."""
    return rng.uniform(0.01, 0.03)


def maybe_null(rng: random.Random, value: Any, rate: float) -> Any:
    return None if rng.random() < rate else value


def daterange(start: date, end: date) -> list[date]:
    if end < start:
        return []
    n = (end - start).days
    return [start + timedelta(days=i) for i in range(n + 1)]


def day_weight_series(
    days: list[date],
    month_weights: dict[int, float],
    weekday_weights: dict[int, float],
    growth_start: float = 1.0,
    growth_end: float = 1.0,
) -> list[float]:
    """Per-day sampling weight combining a linear growth trend with month
    and day-of-week seasonality multipliers."""
    n = len(days)
    out = []
    for i, d in enumerate(days):
        g = growth_start + (growth_end - growth_start) * (i / (n - 1) if n > 1 else 0.0)
        out.append(g * month_weights[d.month] * weekday_weights[d.weekday()])
    return out


def money(value: float) -> str:
    return f"{value:.2f}"


def write_tables(tables: TableSpec, out_dir: Path, prefix: str) -> None:
    for name, (fieldnames, rows) in tables.items():
        path = out_dir / f"{prefix}_{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"  wrote {path}  ({len(rows):,} rows)")


# ---------------------------------------------------------------------------
# E-commerce generators
# ---------------------------------------------------------------------------


def gen_customers(rng: random.Random, n: int, start_date: date, ref_date: date) -> list[Row]:
    email_nr = null_rate(rng)
    region_nr = null_rate(rng)
    channel_nr = null_rate(rng)

    days = daterange(start_date, ref_date)
    weights = day_weight_series(days, FLAT_MONTH, SIGNUP_WEEKDAY_SEASONALITY, 0.35, 1.65)
    signup_dates = sorted(rng.choices(days, weights=weights, k=n))

    rows: list[Row] = []
    for i, signup in enumerate(signup_dates, start=1):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        country = weighted_choice(rng, COUNTRIES, COUNTRY_WEIGHTS)
        region = (
            rng.choice(US_STATES)
            if country == "US"
            else rng.choice(REGIONS_BY_COUNTRY.get(country, ["N/A"]))
        )
        propensity = min(20.0, rng.paretovariate(1.5))
        rows.append(
            {
                "customer_id": f"CUST-{i:06d}",
                "first_name": first,
                "last_name": last,
                "email": maybe_null(
                    rng, f"{first.lower()}.{last.lower()}{i}@example.com", email_nr
                ),
                "signup_date": signup.isoformat(),
                "country": country,
                "region": maybe_null(rng, region, region_nr),
                "customer_segment": weighted_choice(
                    rng, CUSTOMER_SEGMENTS, CUSTOMER_SEGMENT_WEIGHTS
                ),
                "marketing_channel": maybe_null(
                    rng,
                    weighted_choice(rng, MARKETING_CHANNELS, MARKETING_CHANNEL_WEIGHTS),
                    channel_nr,
                ),
                "_signup_date_obj": signup,
                "_propensity": propensity,
            }
        )
    return rows


def gen_products(rng: random.Random, n: int, start_date: date, ref_date: date) -> list[Row]:
    weight_nr = null_rate(rng)
    categories = list(CATEGORY_SUBCATS)
    history_start = start_date - timedelta(days=365)

    rows: list[Row] = []
    for i in range(1, n + 1):
        category = weighted_choice(rng, categories, CATEGORY_WEIGHTS)
        subcat = rng.choice(CATEGORY_SUBCATS[category])
        brand = rng.choice(BRANDS)
        descriptor = rng.choice(PRODUCT_DESCRIPTORS)
        product_name = f"{brand} {descriptor} {subcat}"

        lo, hi = COST_RANGE_BY_CATEGORY[category]
        unit_cost = round(rng.uniform(lo, hi), 2)
        margin = rng.uniform(1.35, 2.3)
        unit_price = round(unit_cost * margin, 2)

        launch_date = rng.choice(daterange(history_start, ref_date - timedelta(days=1)))
        effective_launch = max(launch_date, start_date)
        is_active = rng.random() < 0.92
        popularity = min(15.0, rng.paretovariate(1.3))

        rows.append(
            {
                "product_id": f"PROD-{i:04d}",
                "product_name": product_name,
                "category": category,
                "subcategory": subcat,
                "brand": brand,
                "unit_cost": money(unit_cost),
                "unit_price": money(unit_price),
                "launch_date": launch_date.isoformat(),
                "is_active": "true" if is_active else "false",
                "weight_kg": maybe_null(rng, f"{rng.uniform(0.05, 12.0):.2f}", weight_nr),
                "_launch_date_obj": effective_launch,
                "_popularity": popularity,
            }
        )
    return rows


def gen_orders_and_items(
    rng: random.Random,
    customers: list[Row],
    products: list[Row],
    start_date: date,
    ref_date: date,
    n_orders: int,
) -> tuple[list[Row], list[Row]]:
    payment_nr = null_rate(rng)
    discount_code_rate = 0.14  # business sparsity: most orders have no promo code

    signup_dates_sorted = [c["_signup_date_obj"] for c in customers]
    customer_ids = [c["customer_id"] for c in customers]
    propensities = [c["_propensity"] for c in customers]
    customer_country = {c["customer_id"]: c["country"] for c in customers}

    product_ids = [p["product_id"] for p in products]
    product_pop = [p["_popularity"] for p in products]
    product_launch = [p["_launch_date_obj"] for p in products]
    product_price = {p["product_id"]: float(p["unit_price"]) for p in products}

    days = daterange(start_date, ref_date)
    weights = day_weight_series(
        days, ORDER_MONTH_SEASONALITY, ORDER_WEEKDAY_SEASONALITY, 0.45, 1.55
    )
    order_dates = sorted(rng.choices(days, weights=weights, k=n_orders))

    hours = list(range(24))
    orders: list[Row] = []
    order_items: list[Row] = []
    order_item_seq = 1

    for i, order_date in enumerate(order_dates, start=1):
        idx = bisect.bisect_right(signup_dates_sorted, order_date)
        idx = max(idx, 1)
        pool_ids = customer_ids[:idx]
        pool_weights = propensities[:idx]
        customer_id = weighted_choice(rng, pool_ids, pool_weights)

        hour = weighted_choice(rng, hours, ORDER_HOUR_WEIGHTS)
        order_dt = datetime(
            order_date.year,
            order_date.month,
            order_date.day,
            hour,
            rng.randint(0, 59),
            rng.randint(0, 59),
        )

        days_to_ref = (ref_date - order_date).days
        if days_to_ref <= 3 and rng.random() < 0.35:
            status = "pending"
        else:
            status = weighted_choice(rng, ["completed", "cancelled"], [93, 7])

        channel = weighted_choice(rng, CHANNELS_ORD, CHANNEL_WEIGHTS_ORD)
        payment_method = maybe_null(
            rng, weighted_choice(rng, PAYMENT_METHODS, PAYMENT_WEIGHTS), payment_nr
        )

        cust_country = customer_country[customer_id]
        shipping_country = (
            weighted_choice(rng, COUNTRIES, COUNTRY_WEIGHTS)
            if rng.random() < 0.06
            else cust_country
        )
        discount_code = f"SAVE{rng.randint(10, 30)}" if rng.random() < discount_code_rate else None

        order_id = f"ORD-{i:07d}"

        eligible_idx = [j for j, launch in enumerate(product_launch) if launch <= order_date]
        if not eligible_idx:
            eligible_idx = list(range(len(product_ids)))

        n_items = weighted_choice(rng, [1, 2, 3, 4, 5], [45, 28, 15, 8, 4])
        chosen: set[int] = set()
        line_totals: list[float] = []

        for _ in range(n_items):
            elig_weights = [product_pop[j] for j in eligible_idx]
            j = weighted_choice(rng, eligible_idx, elig_weights)
            attempts = 0
            while j in chosen and attempts < 5:
                j = weighted_choice(rng, eligible_idx, elig_weights)
                attempts += 1
            chosen.add(j)

            pid = product_ids[j]
            base_price = product_price[pid]
            qty = weighted_choice(rng, [1, 2, 3], [70, 22, 8])
            price_noise = rng.uniform(0.95, 1.05)
            unit_price_at_order = round(base_price * price_noise, 2)
            discount_pct = round(rng.uniform(0.05, 0.30), 2) if rng.random() < 0.12 else 0.0
            line_total = round(qty * unit_price_at_order * (1 - discount_pct), 2)

            order_items.append(
                {
                    "order_item_id": f"OITM-{order_item_seq:08d}",
                    "order_id": order_id,
                    "product_id": pid,
                    "quantity": qty,
                    "unit_price": money(unit_price_at_order),
                    "discount_pct": f"{discount_pct:.2f}",
                    "line_total": money(line_total),
                }
            )
            line_totals.append(line_total)
            order_item_seq += 1

        order_total = round(sum(line_totals), 2)

        orders.append(
            {
                "order_id": order_id,
                "customer_id": customer_id,
                "order_date": order_dt.isoformat(sep=" "),
                "order_status": status,
                "channel": channel,
                "payment_method": payment_method,
                "shipping_country": shipping_country,
                "discount_code": discount_code,
                "order_total": money(order_total),
                "currency": "USD",
                "_order_date_obj": order_date,
            }
        )

    return orders, order_items


def gen_returns(
    rng: random.Random, orders: list[Row], order_items: list[Row], ref_date: date
) -> list[Row]:
    reason_nr = null_rate(rng)
    orders_by_id = {o["order_id"]: o for o in orders}
    eligible_items = [
        oi for oi in order_items if orders_by_id[oi["order_id"]]["order_status"] == "completed"
    ]

    n_returns = int(len(eligible_items) * RETURN_RATE)
    chosen = rng.sample(eligible_items, k=min(n_returns, len(eligible_items)))

    rows: list[Row] = []
    for i, oi in enumerate(chosen, start=1):
        order = orders_by_id[oi["order_id"]]
        order_date = order["_order_date_obj"]
        max_delay = max(1, (ref_date - order_date).days)
        return_date = order_date + timedelta(days=rng.randint(1, min(30, max_delay)))
        return_date = min(return_date, ref_date)

        status = weighted_choice(
            rng, ["completed", "approved", "requested", "rejected"], [55, 15, 22, 8]
        )
        line_total = float(oi["line_total"])
        refund_amount = line_total if status in ("completed", "approved") else 0.0

        rows.append(
            {
                "return_id": f"RET-{i:06d}",
                "order_id": oi["order_id"],
                "order_item_id": oi["order_item_id"],
                "return_date": return_date.isoformat(),
                "return_reason": maybe_null(
                    rng, weighted_choice(rng, RETURN_REASONS, RETURN_REASON_WEIGHTS), reason_nr
                ),
                "return_status": status,
                "refund_amount": money(refund_amount),
            }
        )
    return rows


def build_ecommerce(seed: int, ref_date: date) -> TableSpec:
    start_date = ref_date - timedelta(days=ECOMMERCE_HISTORY_DAYS)

    customers = gen_customers(
        rng_for(seed, "ecommerce.customers"), N_CUSTOMERS, start_date, ref_date
    )
    products = gen_products(rng_for(seed, "ecommerce.products"), N_PRODUCTS, start_date, ref_date)
    orders, order_items = gen_orders_and_items(
        rng_for(seed, "ecommerce.orders"),
        customers,
        products,
        start_date,
        ref_date,
        N_ORDERS,
    )
    returns = gen_returns(rng_for(seed, "ecommerce.returns"), orders, order_items, ref_date)

    return {
        "customers": (CUSTOMERS_FIELDS, customers),
        "products": (PRODUCTS_FIELDS, products),
        "orders": (ORDERS_FIELDS, orders),
        "order_items": (ORDER_ITEMS_FIELDS, order_items),
        "returns": (RETURNS_FIELDS, returns),
    }


# ---------------------------------------------------------------------------
# SaaS generators
# ---------------------------------------------------------------------------


def gen_accounts(rng: random.Random, n: int, start_date: date, ref_date: date) -> list[Row]:
    owner_nr = null_rate(rng)
    owners = [f"csm{k}@omniagent-vendor.example.com" for k in range(1, 9)]

    days = daterange(start_date, ref_date)
    weights = day_weight_series(days, FLAT_MONTH, FLAT_WEEKDAY, 0.3, 1.7)
    signup_dates = sorted(rng.choices(days, weights=weights, k=n))

    rows: list[Row] = []
    for i, signup in enumerate(signup_dates, start=1):
        account_name = (
            f"{rng.choice(COMPANY_ADJ)}{rng.choice(COMPANY_NOUN)} {rng.choice(COMPANY_SUFFIX)}"
        )
        rows.append(
            {
                "account_id": f"ACC-{i:05d}",
                "account_name": account_name,
                "industry": weighted_choice(rng, INDUSTRIES, INDUSTRY_WEIGHTS),
                "company_size": weighted_choice(rng, COMPANY_SIZES, COMPANY_SIZE_WEIGHTS),
                "country": weighted_choice(rng, SAAS_COUNTRIES, SAAS_COUNTRY_WEIGHTS),
                "signup_date": signup.isoformat(),
                "account_owner_email": maybe_null(rng, rng.choice(owners), owner_nr),
                "is_active": "true",  # patched in gen_subscriptions once churn is known
                "churn_date": None,  # patched in gen_subscriptions once churn is known
                "_signup_date_obj": signup,
                "_churn_date_obj": None,
            }
        )
    return rows


def _plan_weights_for_era(base_weights: list[float], era: int) -> list[float]:
    """First era uses the account-size plan mix as-is; later eras (upgrades /
    renewals) skew toward the higher tiers, modelling expansion over time."""
    if era == 0:
        return base_weights
    return [w * (1.3 if idx >= 2 else 0.8) for idx, w in enumerate(base_weights)]


def _price_subscription(rng: random.Random, plan: str) -> tuple[str, int, float, float]:
    """Roll billing_cycle/seats/discount for one subscription era and return
    (billing_cycle, seats, mrr_amount, discount_pct)."""
    billing_cycle = weighted_choice(rng, ["monthly", "annual"], [70, 30])
    seats = rng.randint(*PLAN_SEATS_RANGE[plan])
    price_per_seat = rng.uniform(*PLAN_PRICE_PER_SEAT[plan])
    base_mrr = seats * price_per_seat
    discount_pct = (
        round(rng.uniform(0.05, 0.20), 2) if (plan == "Enterprise" and rng.random() < 0.4) else 0.0
    )

    effective_mrr = base_mrr * (1 - discount_pct)
    if billing_cycle == "annual":
        effective_mrr *= 1 - ANNUAL_DISCOUNT
    return billing_cycle, seats, round(effective_mrr, 2), discount_pct


def _decide_lifecycle(
    rng: random.Random, start: date, is_last: bool, ref_date: date
) -> tuple[str, date | None]:
    """Decide a subscription era's status and end_date.

    Non-final eras always end (superseded by the next era). The final era
    per account may still be trialing, may churn before ref_date, or may
    still be active as of ref_date.
    """
    if not is_last:
        tenure = int(rng.uniform(60, 400))
        end = start + timedelta(days=tenure)
        if end >= ref_date:
            end = ref_date - timedelta(days=1)
        return "cancelled", end

    if start >= ref_date - timedelta(days=14) and rng.random() < 0.18:
        return "trialing", None
    if rng.random() < 0.24:
        tenure = int(rng.uniform(30, 540))
        end = start + timedelta(days=tenure)
        if end >= ref_date:
            end = ref_date - timedelta(days=rng.randint(1, 20))
        return "cancelled", end
    return "active", None


def gen_subscriptions(rng: random.Random, accounts: list[Row], ref_date: date) -> list[Row]:
    subs: list[Row] = []
    seq = 1

    for acct in accounts:
        signup = acct["_signup_date_obj"]
        size = acct["company_size"]
        cursor = signup + timedelta(days=rng.randint(0, 10))
        r = rng.random()
        eras = 1 if r < 0.55 else (2 if r < 0.85 else 3)
        base_plan_weights = PLAN_BY_SIZE_WEIGHTS[size]

        acct_subs: list[Row] = []
        for era in range(eras):
            if cursor >= ref_date:
                break
            is_last = era == eras - 1
            plan_weights = _plan_weights_for_era(base_plan_weights, era)
            plan = weighted_choice(rng, PLAN_NAMES, plan_weights)
            billing_cycle, seats, mrr_amount, discount_pct = _price_subscription(rng, plan)

            start_date_sub = cursor
            status, end_date_sub = _decide_lifecycle(rng, start_date_sub, is_last, ref_date)

            sub_id = f"SUB-{seq:06d}"
            seq += 1
            row: Row = {
                "subscription_id": sub_id,
                "account_id": acct["account_id"],
                "plan_name": plan,
                "billing_cycle": billing_cycle,
                "seats": seats,
                "mrr_amount": money(mrr_amount),
                "discount_pct": f"{discount_pct:.2f}",
                "start_date": start_date_sub.isoformat(),
                "end_date": end_date_sub.isoformat() if end_date_sub else None,
                "status": status,
                "_start_date_obj": start_date_sub,
                "_end_date_obj": end_date_sub,
                "_is_last_era": is_last,
                "_mrr_amount_num": mrr_amount,
            }
            acct_subs.append(row)
            subs.append(row)

            if end_date_sub is None:
                break
            cursor = end_date_sub + timedelta(days=1)

        final_churn = None
        for s in acct_subs:
            if s["_is_last_era"] and s["status"] == "cancelled":
                final_churn = s["_end_date_obj"]
        acct["_churn_date_obj"] = final_churn
        acct["churn_date"] = final_churn.isoformat() if final_churn else None
        acct["is_active"] = "false" if final_churn else "true"

    return subs


def gen_invoices(rng: random.Random, subs: list[Row], ref_date: date) -> list[Row]:
    pm_nr = null_rate(rng)
    invoices: list[Row] = []
    seq = 1

    for s in subs:
        if s["status"] == "trialing":
            continue  # no billing during trial

        start = s["_start_date_obj"]
        end = s["_end_date_obj"] or ref_date
        cycle = s["billing_cycle"]
        mrr = s["_mrr_amount_num"]

        cur = date(start.year, start.month, 1) if cycle == "monthly" else start

        guard = 0
        while cur <= end and cur <= ref_date and guard < 400:
            guard += 1
            invoice_date = cur + timedelta(days=rng.randint(0, 2))
            if invoice_date > ref_date:
                break

            amount_due = round(mrr if cycle == "monthly" else mrr * 12, 2)
            due_term = 14 if cycle == "monthly" else 30
            due_date = invoice_date + timedelta(days=due_term)
            age = (ref_date - invoice_date).days

            if age > 30:
                status = weighted_choice(rng, ["paid", "void", "refunded"], [95, 3, 2])
            else:
                status = weighted_choice(rng, ["paid", "open", "overdue"], [62, 30, 8])
            amount_paid = amount_due if status in ("paid", "refunded") else 0.0

            invoices.append(
                {
                    "invoice_id": f"INV-{seq:07d}",
                    "account_id": s["account_id"],
                    "subscription_id": s["subscription_id"],
                    "invoice_date": invoice_date.isoformat(),
                    "due_date": due_date.isoformat(),
                    "amount_due": money(amount_due),
                    "amount_paid": money(amount_paid),
                    "status": status,
                    "payment_method": maybe_null(
                        rng, weighted_choice(rng, PAYMENT_METHODS_SAAS, PAYMENT_WEIGHTS_SAAS), pm_nr
                    ),
                }
            )
            seq += 1

            if cycle == "monthly":
                y, m = cur.year, cur.month
                m += 1
                if m == 13:
                    m, y = 1, y + 1
                cur = date(y, m, 1)
            else:
                cur = cur + timedelta(days=365)

    return invoices


def gen_usage_events(rng: random.Random, subs: list[Row], ref_date: date) -> list[Row]:
    dur_nr = null_rate(rng)
    hours = list(range(24))
    events: list[Row] = []
    seq = 1

    for s in subs:
        start = s["_start_date_obj"]
        end = min(s["_end_date_obj"] or ref_date, ref_date)
        days = daterange(start, end)
        if len(days) < 2:
            continue

        weights = day_weight_series(
            days, SAAS_MONTH_SEASONALITY, SAAS_WEEKDAY_SEASONALITY, 1.0, 1.0
        )
        plan_factor = PLAN_ACTIVITY_FACTOR.get(s["plan_name"], 1.0)
        base_rate = rng.uniform(0.35, 0.75)
        target_n = int(min(220, max(4, len(days) * base_rate * plan_factor / 6)))
        event_dates = rng.choices(days, weights=weights, k=target_n)

        for d in event_dates:
            etype = weighted_choice(rng, EVENT_TYPES, EVENT_WEIGHTS)
            hour = weighted_choice(rng, hours, SAAS_HOUR_WEIGHTS)
            ts = datetime(d.year, d.month, d.day, hour, rng.randint(0, 59), rng.randint(0, 59))
            duration = None
            if etype in ("report_generated", "data_export", "dashboard_view"):
                duration = maybe_null(rng, rng.randint(5, 600), dur_nr)

            events.append(
                {
                    "event_id": f"EVT-{seq:08d}",
                    "account_id": s["account_id"],
                    "subscription_id": s["subscription_id"],
                    "event_timestamp": ts.isoformat(sep=" "),
                    "event_type": etype,
                    "event_count": 1,
                    "duration_seconds": duration,
                }
            )
            seq += 1

    return events


def gen_support_tickets(rng: random.Random, accounts: list[Row], ref_date: date) -> list[Row]:
    agent_nr = null_rate(rng)
    agents = [f"agent{k}@omniagent-support.example.com" for k in range(1, 13)]
    hours = list(range(24))
    tickets: list[Row] = []
    seq = 1

    for acct in accounts:
        start = acct["_signup_date_obj"]
        end = min(acct["_churn_date_obj"] or ref_date, ref_date)
        days = daterange(start, end)
        if not days:
            continue

        weights = day_weight_series(
            days, SAAS_MONTH_SEASONALITY, SAAS_WEEKDAY_SEASONALITY, 0.7, 1.3
        )
        tenure_months = max(1.0, len(days) / 30)
        size_factor = SIZE_TICKET_FACTOR.get(acct["company_size"], 1.0)
        n_tickets = int(max(0, rng.uniform(0.4, 1.1) * tenure_months * size_factor))
        if n_tickets == 0:
            continue

        ticket_dates = rng.choices(days, weights=weights, k=n_tickets)
        for d in ticket_dates:
            hour = weighted_choice(rng, hours, SAAS_HOUR_WEIGHTS)
            created = datetime(d.year, d.month, d.day, hour, rng.randint(0, 59), rng.randint(0, 59))
            category = weighted_choice(rng, TICKET_CATEGORIES, TICKET_CATEGORY_WEIGHTS)
            priority = weighted_choice(rng, TICKET_PRIORITIES, TICKET_PRIORITY_WEIGHTS)

            recent = (ref_date - d).days <= 3
            if recent and rng.random() < 0.5:
                status = weighted_choice(rng, ["open", "in_progress"], [55, 45])
            else:
                status = weighted_choice(rng, ["resolved", "closed", "in_progress"], [55, 40, 5])

            resolved_at = None
            csat = None
            if status in ("resolved", "closed"):
                resolve_hours = {
                    "urgent": rng.uniform(1, 8),
                    "high": rng.uniform(4, 24),
                    "medium": rng.uniform(12, 72),
                    "low": rng.uniform(24, 120),
                }[priority]
                resolved_dt = created + timedelta(hours=resolve_hours)
                if resolved_dt.date() > ref_date:
                    resolved_dt = datetime.combine(ref_date, created.time())
                resolved_at = resolved_dt.isoformat(sep=" ")
                if rng.random() < 0.68:  # business sparsity: not every closed ticket gets rated
                    csat = weighted_choice(rng, [1, 2, 3, 4, 5], [5, 8, 17, 35, 35])

            tickets.append(
                {
                    "ticket_id": f"TIC-{seq:06d}",
                    "account_id": acct["account_id"],
                    "created_at": created.isoformat(sep=" "),
                    "category": category,
                    "priority": priority,
                    "status": status,
                    "resolved_at": resolved_at,
                    "satisfaction_score": csat,
                    "assigned_agent_email": maybe_null(rng, rng.choice(agents), agent_nr),
                }
            )
            seq += 1

    return tickets


def build_saas(seed: int, ref_date: date) -> TableSpec:
    start_date = ref_date - timedelta(days=SAAS_HISTORY_DAYS)

    accounts = gen_accounts(rng_for(seed, "saas.accounts"), N_ACCOUNTS, start_date, ref_date)
    subs = gen_subscriptions(rng_for(seed, "saas.subscriptions"), accounts, ref_date)
    invoices = gen_invoices(rng_for(seed, "saas.invoices"), subs, ref_date)
    usage_events = gen_usage_events(rng_for(seed, "saas.usage_events"), subs, ref_date)
    tickets = gen_support_tickets(rng_for(seed, "saas.support_tickets"), accounts, ref_date)

    return {
        "accounts": (ACCOUNTS_FIELDS, accounts),
        "subscriptions": (SUBSCRIPTIONS_FIELDS, subs),
        "invoices": (INVOICES_FIELDS, invoices),
        "usage_events": (USAGE_EVENTS_FIELDS, usage_events),
        "support_tickets": (SUPPORT_TICKETS_FIELDS, tickets),
    }


# ---------------------------------------------------------------------------
# Referential integrity verification
# ---------------------------------------------------------------------------


def _check(label: str, rows: list[Row], field: str, valid_ids: set[str]) -> bool:
    bad = sum(1 for r in rows if r[field] not in valid_ids)
    ok = bad == 0
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  ({len(rows):,} rows checked, {bad} violations)")
    return ok


def _check_consistency(label: str, count: int, mismatches: int) -> bool:
    ok = mismatches == 0
    print(
        f"  [{'PASS' if ok else 'FAIL'}] {label}  ({count:,} rows checked, {mismatches} mismatches)"
    )
    return ok


def verify_ecommerce_ri(tables: TableSpec) -> bool:
    _, customers = tables["customers"]
    _, products = tables["products"]
    _, orders = tables["orders"]
    _, order_items = tables["order_items"]
    _, returns = tables["returns"]

    customer_ids = {c["customer_id"] for c in customers}
    product_ids = {p["product_id"] for p in products}
    order_ids = {o["order_id"] for o in orders}
    order_item_ids = {oi["order_item_id"] for oi in order_items}
    order_item_by_id = {oi["order_item_id"]: oi for oi in order_items}

    ok = True
    ok &= _check("orders.customer_id -> customers.customer_id", orders, "customer_id", customer_ids)
    ok &= _check("order_items.order_id -> orders.order_id", order_items, "order_id", order_ids)
    ok &= _check(
        "order_items.product_id -> products.product_id", order_items, "product_id", product_ids
    )
    ok &= _check("returns.order_id -> orders.order_id", returns, "order_id", order_ids)
    ok &= _check(
        "returns.order_item_id -> order_items.order_item_id",
        returns,
        "order_item_id",
        order_item_ids,
    )

    mismatches = sum(
        1
        for r in returns
        if r["order_item_id"] in order_item_by_id
        and order_item_by_id[r["order_item_id"]]["order_id"] != r["order_id"]
    )
    ok &= _check_consistency(
        "returns.order_id matches order_items.order_id", len(returns), mismatches
    )
    return ok


def verify_saas_ri(tables: TableSpec) -> bool:
    _, accounts = tables["accounts"]
    _, subs = tables["subscriptions"]
    _, invoices = tables["invoices"]
    _, usage_events = tables["usage_events"]
    _, tickets = tables["support_tickets"]

    account_ids = {a["account_id"] for a in accounts}
    sub_ids = {s["subscription_id"] for s in subs}
    sub_by_id = {s["subscription_id"]: s for s in subs}

    ok = True
    ok &= _check("subscriptions.account_id -> accounts.account_id", subs, "account_id", account_ids)
    ok &= _check("invoices.account_id -> accounts.account_id", invoices, "account_id", account_ids)
    ok &= _check(
        "invoices.subscription_id -> subscriptions.subscription_id",
        invoices,
        "subscription_id",
        sub_ids,
    )
    ok &= _check(
        "usage_events.account_id -> accounts.account_id", usage_events, "account_id", account_ids
    )
    ok &= _check(
        "usage_events.subscription_id -> subscriptions.subscription_id",
        usage_events,
        "subscription_id",
        sub_ids,
    )
    ok &= _check(
        "support_tickets.account_id -> accounts.account_id", tickets, "account_id", account_ids
    )

    inv_mismatches = sum(
        1
        for inv in invoices
        if inv["subscription_id"] in sub_by_id
        and sub_by_id[inv["subscription_id"]]["account_id"] != inv["account_id"]
    )
    ok &= _check_consistency(
        "invoices.account_id matches subscriptions.account_id", len(invoices), inv_mismatches
    )

    evt_mismatches = sum(
        1
        for e in usage_events
        if e["subscription_id"] in sub_by_id
        and sub_by_id[e["subscription_id"]]["account_id"] != e["account_id"]
    )
    ok &= _check_consistency(
        "usage_events.account_id matches subscriptions.account_id",
        len(usage_events),
        evt_mismatches,
    )

    return ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deterministic e-commerce and SaaS sample-data generator (OmniAgent 2.0).",
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help="RNG seed (default: %(default)s)"
    )
    parser.add_argument(
        "--ref-date",
        type=str,
        default=DEFAULT_REF_DATE.isoformat(),
        help="As-of date, YYYY-MM-DD; all generated history is <= this date (default: %(default)s)",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=str(DEFAULT_OUT_DIR),
        help="Output directory for CSVs (default: %(default)s)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ref_date = datetime.strptime(args.ref_date, "%Y-%m-%d").date()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"OmniAgent sample data generator  seed={args.seed}  ref_date={ref_date.isoformat()}")
    print("=" * 72)

    print("\n[e-commerce]")
    ecom_tables = build_ecommerce(args.seed, ref_date)
    write_tables(ecom_tables, out_dir, "ecommerce")

    print("\n[saas]")
    saas_tables = build_saas(args.seed, ref_date)
    write_tables(saas_tables, out_dir, "saas")

    print("\n" + "=" * 72)
    print("Row counts:")
    for prefix, tables in (("ecommerce", ecom_tables), ("saas", saas_tables)):
        for name, (_fields, rows) in tables.items():
            print(f"  {prefix}_{name:<16s} {len(rows):>8,d} rows")

    print("\nReferential integrity checks:")
    print(" -- e-commerce --")
    ok_ecom = verify_ecommerce_ri(ecom_tables)
    print(" -- saas --")
    ok_saas = verify_saas_ri(saas_tables)

    print("\n" + "=" * 72)
    if ok_ecom and ok_saas:
        print(f"PASS: all referential integrity checks passed (seed={args.seed}, deterministic).")
        return 0
    print("FAIL: referential integrity violations detected -- see checks above.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
