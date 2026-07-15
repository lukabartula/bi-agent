# BI Agent — Olist E-Commerce Data Warehouse

## Project

IT 501 Business Intelligence final exam. Build a star-schema data warehouse on
Supabase (PostgreSQL) from the Olist Brazilian e-commerce dataset, expose it to
this CLI agent via a Postgres MCP server, and build dashboards in Apache Superset
via the Superset MCP server.

Adapted from the `dinokeco/bi-agent` reference project, which did the same for the
Online Retail dataset using the Gemini CLI. This fork uses Claude Code instead.

## SQL generation rules

@AGENT_SYSTEM_PROMPT.md governs all SQL generation against the Olist warehouse via
the `olist-warehouse` MCP tools (`get_schema`, `run_query`, `sample_rows`). Read it
before writing any SQL against this warehouse — it covers schema-check discipline,
showing your SQL, the `customer_unique_id` vs `customer_id` trap, AOV grain,
`day_of_week` convention, and how to handle ambiguous questions.

## Stack

- **Warehouse**: Supabase (hosted PostgreSQL)
- **ETL**: Python 3.10+, pandas, psycopg2
- **Agent**: Claude Code + Postgres MCP + Superset MCP
- **BI**: Apache Superset

## Source data

Olist Brazilian E-Commerce dataset (Kaggle: `olistbr/brazilian-ecommerce`).
CSVs live in `data/` and are gitignored — never commit them.

Files:
- `olist_orders_dataset.csv`
- `olist_order_items_dataset.csv`
- `olist_customers_dataset.csv`
- `olist_products_dataset.csv`
- `olist_sellers_dataset.csv`
- `olist_order_payments_dataset.csv`
- `olist_order_reviews_dataset.csv`
- `olist_geolocation_dataset.csv`
- `product_category_name_translation.csv`

**Always inspect real CSV headers before writing code against them.** This dataset
has known quirks, including misspelled columns (e.g. `product_name_lenght`).

## Star schema

Grain of the fact table: **one row per order item** (i.e. per product line within
an order). This is the finest natural grain and lets every revenue metric roll up
from it.

**Facts** (two facts sharing dimensions = fact constellation)

- `fact_order_items` — grain: one row per order item. Measures: `price`, `freight_value`,
  `total_item_value` (GENERATED ALWAYS AS (price + freight_value) STORED).
  - FKs: `product_key`, `customer_key`, `seller_key`, `order_date_key`, `order_key`
  - Degenerate dims: `order_id`, `order_item_id`
  - `order_date_key` is driven by **`order_purchase_timestamp`** (date part) — the
    transaction date. Not approved/delivered.
  - `customer_key` requires a two-hop join: order_items -> orders (for customer_id)
    -> dim_customer. Keep it denormalized on the fact anyway, so customer slicing
    doesn't drag dim_order into every query.
  - **Do not include `total_item_value` in INSERT column lists** — it's generated.

- `fact_reviews` — grain: one row per `(review_id, order_id)`. Measure: `review_score`.
  - FK: `order_key`. Natural key: **`(review_id, order_id)`** (UNIQUE) — NOT `review_id` alone.
  - **Verified against the data**: 789 `review_id` values appear on 2-3 rows each (814 extra
    rows total), and *every one maps to a different `order_id`*. Zero same-order duplicates.
    Olist reuses review_id values across unrelated orders. Deduping on `review_id` alone
    would silently destroy 814 real review-order relationships with no error raised.
    Drop only true full-row duplicates.
  - Do NOT flatten review score onto dim_order — orders can have more than one review,
    and that would conflate grain.

- `fact_payments` — grain: one row per `(order_id, payment_sequential)`.
  Measures: `payment_value`, `payment_installments`. Attribute: `payment_type`.
  - FK: `order_key`. Natural key: `(order_id, payment_sequential)` (UNIQUE).
  - Optional/lowest priority: cut this first if time-pressed. It exists to feed the
    Phase 5 "hidden insights" (e.g. installment behaviour vs review scores).

**Dimensions**
- `dim_customer` — customer_id (natural), customer_unique_id, zip prefix, city, state
- `dim_product` — product_id (natural), category (pt + english translation), weight, dimensions
- `dim_seller` — seller_id (natural), zip prefix, city, state
- `dim_date` — full_date (natural, DATE grain), year, quarter, month, day, day_of_week, week
- `dim_order` — order_id (natural), status, purchase/approved/delivered/estimated timestamps,
  plus derived `delivery_days` and `delivery_delay_days`

`dim_order` is what makes this lightly snowflaked rather than a pure star: order-level
attributes live once in their own dimension instead of being repeated on every item row.
This is deliberate — it keeps delivery-performance analysis clean without inflating the fact.

**Deliberately excluded: `olist_geolocation_dataset.csv`.** City/state already live on
dim_customer and dim_seller; geolocation only adds lat/lng, and it has many rows per zip
prefix requiring aggregation. Superset renders Brazil state maps from state codes alone.
This is a scope trade-off to defend in the write-up, not an oversight.

**Conventions**
- Every dimension has a surrogate integer PK named `<dim>_key` (identity column).
- Natural/business keys get a UNIQUE constraint so `ON CONFLICT` makes loads idempotent.
- All FKs are explicitly declared — the rubric grades declared referential integrity.
- Schema: `public`.

**Gotchas confirmed against the real CSVs**
- **Zip prefixes are TEXT, not INTEGER.** Values like `01037` have leading zeros that an
  int cast silently destroys. VARCHAR(5) everywhere.
- **Misspelled source columns**: `product_name_lenght`, `product_description_lenght`.
  Rename on load to `product_name_length` / `product_description_length`.
- **`day_of_week` convention**: use **pandas `.dayofweek`, 0=Monday .. 6=Sunday**.
  Postgres `EXTRACT(DOW)` is 0=Sunday — do NOT mix them. Every day-of-week chart must
  assume 0=Monday. Document this in the column comment.
- **`dim_date` must be a contiguous calendar**, generated from min to max
  `order_purchase_timestamp` — not just dates present in the data. Gaps in a date
  dimension read as zero-revenue days in trend charts, which is wrong.
- `product_category_name` can be NULL, and the translation lookup may not cover every
  category — expect NULL `product_category_name_english` and handle it in charts.
- **Verify referential closure before loading the fact**: confirm every `product_id` and
  `seller_id` in order_items exists in the products/sellers CSVs. An orphan kills the
  FK insert mid-load. (Verified clean: 32,951 products / 3,095 sellers, zero orphans.)
- **Always parse CSVs with a real parser** (pandas / `csv.DictReader`), never naive
  splitting on commas. `review_comment_message` contains free text with embedded commas
  and newlines; naive field splitting shifts columns and produces phantom data errors.
- **`customer_id` is per-order, not per-person.** `customer_unique_id` identifies the
  actual human. `dim_customer` is at `customer_id` grain (~99k rows, roughly one per
  order), so `COUNT(DISTINCT customer_id)` counts ORDERS, not customers. Any customer
  count, repeat-purchase rate, or Customer Lifetime Value metric MUST use
  `customer_unique_id`.

## ETL conventions

Follow the reference pattern in `etl_process.py`:
- Load dimensions first, then read back surrogate keys into dicts, then map the fact.
- Batch inserts (1000 rows) via `psycopg2.extras.execute_values`.
- Idempotent: `ON CONFLICT ... DO NOTHING` everywhere.
- Deduplicate and handle nulls before insert (Olist has orders with no delivery date —
  these are legitimately unshipped/cancelled, do not drop them blindly).
- Convert numpy types to native Python before insert.
- Log progress per batch.

## Environment

Python runs in a virtualenv at `.venv/` (gitignored). **Always `source .venv/bin/activate`
before running any Python.** Ubuntu 24 blocks system-wide pip (PEP 668), and `python`
only exists inside the venv — outside it, it's `python3`.

Installed: pandas 3.0.3, psycopg2-binary, python-dotenv.

Note pandas is 3.x, not 2.x. Copy-on-write is the default (chained assignment won't
propagate), and string columns load as `str` dtype rather than `object`. The upstream
`etl_process.py` was written for pandas 2.x — treat it as a pattern reference, not
code to run verbatim.

## Database connection

Credentials in `.env` (gitignored):

```
POSTGRES_HOST=
POSTGRES_PORT=5432
POSTGRES_DATABASE=postgres
POSTGRES_USER=
POSTGRES_PASSWORD=
```

**Use the Session pooler connection (port 5432), from Supabase dashboard → Connect
→ Session pooler.** Host looks like `aws-0-<region>.pooler.supabase.com`.

Why not the other two:
- **Direct** (`db.<ref>.supabase.co:5432`) is IPv6-only on the free tier. WSL2 and
  many networks are IPv4-only, so this fails with `Network is unreachable`.
- **Transaction pooler** (port `6543`) does not support prepared statements, which
  psycopg2 relies on during batch loads. It will break the ETL.
- **Session pooler** (port `5432`) is IPv4, supports prepared statements, and
  behaves nearly identically to a direct connection. This is the correct choice.

Note: the pooler username is `postgres.<project-ref>` (with the dot and ref), not
plain `postgres`.

## Business metrics (for Superset)

- **Total Revenue** — SUM(total_item_value)
- **Average Order Value** — revenue / distinct orders
- **Month-over-Month Growth** — revenue trend by month
- **Average Delivery Days** — mean(delivered - purchased)
- **Late Delivery Rate** — % of orders delivered after estimated date
- **Review Score Average** — mean review score, sliceable by category/state
- **Revenue by State / Category / Seller** — geographic and catalogue breakdowns

## Dashboards (three, per rubric)

1. **Executive Overview** — revenue, AOV, order volume, MoM trend, top categories
2. **Operational Deep-Dive** — delivery performance, seller metrics, freight costs
3. **Trend/Anomaly Monitor** — late deliveries, review-score dips, outlier detection

## Non-negotiables

- Never commit `data/`, `.env`, or any credentials.
- Don't touch `OnlineRetail.csv` / `etl_process.py` from the upstream repo as a data
  source — they're the reference implementation, kept for provenance only.
