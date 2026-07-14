import logging
import os

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

DATA_DIR = 'data'


def get_connection():
    """Establishes a connection to the PostgreSQL database (Supabase session pooler)."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DATABASE"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def insert_batches(cur, query, data, batch_size=1000, table_name=""):
    """Inserts data in batches and logs progress."""
    total = len(data)
    if total == 0:
        logging.info(f"No data to insert into {table_name}.")
        return

    for i in range(0, total, batch_size):
        batch = data[i:i + batch_size]
        execute_values(cur, query, batch)
        logging.info(f"Inserted {min(i + batch_size, total)}/{total} rows into {table_name}")


def to_native(value):
    """Converts pandas/numpy scalars (including NaN/NaT) to native Python types or None."""
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def to_int(value):
    """Converts a possibly-NaN numeric value to a native int, or None."""
    if pd.isna(value):
        return None
    return int(value)


def load_csvs():
    """Reads every source CSV with pandas' real CSV parser (handles quoting, embedded
    commas/newlines in free-text fields correctly, unlike naive comma-splitting)."""
    orders = pd.read_csv(
        f'{DATA_DIR}/olist_orders_dataset.csv',
        dtype={'order_id': str, 'customer_id': str, 'order_status': str},
        parse_dates=[
            'order_purchase_timestamp', 'order_approved_at',
            'order_delivered_carrier_date', 'order_delivered_customer_date',
            'order_estimated_delivery_date',
        ],
    )
    order_items = pd.read_csv(
        f'{DATA_DIR}/olist_order_items_dataset.csv',
        dtype={'order_id': str, 'product_id': str, 'seller_id': str},
    )
    customers = pd.read_csv(
        f'{DATA_DIR}/olist_customers_dataset.csv',
        dtype={'customer_id': str, 'customer_unique_id': str, 'customer_zip_code_prefix': str},
    )
    products = pd.read_csv(
        f'{DATA_DIR}/olist_products_dataset.csv',
        dtype={'product_id': str, 'product_category_name': str},
    )
    sellers = pd.read_csv(
        f'{DATA_DIR}/olist_sellers_dataset.csv',
        dtype={'seller_id': str, 'seller_zip_code_prefix': str},
    )
    payments = pd.read_csv(
        f'{DATA_DIR}/olist_order_payments_dataset.csv',
        dtype={'order_id': str, 'payment_type': str},
    )
    reviews = pd.read_csv(
        f'{DATA_DIR}/olist_order_reviews_dataset.csv',
        dtype={'review_id': str, 'order_id': str},
        parse_dates=['review_creation_date', 'review_answer_timestamp'],
        encoding='utf-8',
    )
    category_translation = pd.read_csv(
        f'{DATA_DIR}/product_category_name_translation.csv',
        dtype=str,
    )
    return orders, order_items, customers, products, sellers, payments, reviews, category_translation


def load_dim_customer(cur, customers):
    customers = customers.drop_duplicates(subset=['customer_id'])
    data = [
        (
            row.customer_id,
            row.customer_unique_id,
            to_native(row.customer_zip_code_prefix),
            to_native(row.customer_city),
            to_native(row.customer_state),
        )
        for row in customers.itertuples(index=False)
    ]
    insert_batches(cur, """
        INSERT INTO public.dim_customer
            (customer_id, customer_unique_id, customer_zip_code_prefix, customer_city, customer_state)
        VALUES %s
        ON CONFLICT (customer_id) DO NOTHING
    """, data, table_name="dim_customer")


def load_dim_product(cur, products, category_translation):
    merged = products.merge(category_translation, on='product_category_name', how='left')
    merged = merged.drop_duplicates(subset=['product_id'])
    data = [
        (
            row.product_id,
            to_native(row.product_category_name),
            to_native(row.product_category_name_english),
            to_int(row.product_name_lenght),
            to_int(row.product_description_lenght),
            to_int(row.product_photos_qty),
            to_int(row.product_weight_g),
            to_int(row.product_length_cm),
            to_int(row.product_height_cm),
            to_int(row.product_width_cm),
        )
        for row in merged.itertuples(index=False)
    ]
    insert_batches(cur, """
        INSERT INTO public.dim_product
            (product_id, product_category_name, product_category_name_english,
             product_name_length, product_description_length, product_photos_qty,
             product_weight_g, product_length_cm, product_height_cm, product_width_cm)
        VALUES %s
        ON CONFLICT (product_id) DO NOTHING
    """, data, table_name="dim_product")


def load_dim_seller(cur, sellers):
    sellers = sellers.drop_duplicates(subset=['seller_id'])
    data = [
        (
            row.seller_id,
            to_native(row.seller_zip_code_prefix),
            to_native(row.seller_city),
            to_native(row.seller_state),
        )
        for row in sellers.itertuples(index=False)
    ]
    insert_batches(cur, """
        INSERT INTO public.dim_seller
            (seller_id, seller_zip_code_prefix, seller_city, seller_state)
        VALUES %s
        ON CONFLICT (seller_id) DO NOTHING
    """, data, table_name="dim_seller")


def load_dim_date(cur, orders):
    """Contiguous calendar spanning min..max order_purchase_timestamp date — not just
    dates present in the data, so trend charts don't read gaps as zero-revenue days."""
    purchase_dates = orders['order_purchase_timestamp'].dt.normalize()
    full_range = pd.date_range(start=purchase_dates.min(), end=purchase_dates.max(), freq='D')

    data = [
        (
            d.date(),
            d.year,
            (d.month - 1) // 3 + 1,
            d.month,
            d.day,
            d.dayofweek,  # pandas convention: 0=Monday .. 6=Sunday
            d.isocalendar()[1],
        )
        for d in full_range
    ]
    insert_batches(cur, """
        INSERT INTO public.dim_date (full_date, year, quarter, month, day, day_of_week, week)
        VALUES %s
        ON CONFLICT (full_date) DO NOTHING
    """, data, table_name="dim_date")


def load_dim_order(cur, orders):
    orders = orders.drop_duplicates(subset=['order_id'])

    delivery_days = (orders['order_delivered_customer_date'] - orders['order_purchase_timestamp']).dt.days
    delivery_delay_days = (orders['order_delivered_customer_date'] - orders['order_estimated_delivery_date']).dt.days

    data = []
    for row, dd, ddd in zip(orders.itertuples(index=False), delivery_days, delivery_delay_days):
        data.append((
            row.order_id,
            to_native(row.order_status),
            to_native(row.order_purchase_timestamp),
            to_native(row.order_approved_at),
            to_native(row.order_delivered_carrier_date),
            to_native(row.order_delivered_customer_date),
            to_native(row.order_estimated_delivery_date),
            to_int(dd),
            to_int(ddd),
        ))

    insert_batches(cur, """
        INSERT INTO public.dim_order
            (order_id, order_status, order_purchase_timestamp, order_approved_at,
             order_delivered_carrier_date, order_delivered_customer_date,
             order_estimated_delivery_date, delivery_days, delivery_delay_days)
        VALUES %s
        ON CONFLICT (order_id) DO NOTHING
    """, data, table_name="dim_order")


def fetch_key_maps(cur):
    cur.execute("SELECT product_key, product_id FROM public.dim_product")
    product_map = {row[1]: row[0] for row in cur.fetchall()}

    cur.execute("SELECT customer_key, customer_id FROM public.dim_customer")
    customer_map = {row[1]: row[0] for row in cur.fetchall()}

    cur.execute("SELECT seller_key, seller_id FROM public.dim_seller")
    seller_map = {row[1]: row[0] for row in cur.fetchall()}

    cur.execute("SELECT date_key, full_date FROM public.dim_date")
    date_map = {row[1]: row[0] for row in cur.fetchall()}

    cur.execute("SELECT order_key, order_id FROM public.dim_order")
    order_map = {row[1]: row[0] for row in cur.fetchall()}

    return product_map, customer_map, seller_map, date_map, order_map


def load_fact_order_items(cur, order_items, orders, product_map, customer_map, seller_map, date_map, order_map):
    order_lookup = orders.set_index('order_id')[['customer_id', 'order_purchase_timestamp']]
    merged = order_items.merge(order_lookup, on='order_id', how='left')

    data = []
    skipped = 0
    for row in merged.itertuples(index=False):
        product_key = product_map.get(row.product_id)
        customer_key = customer_map.get(row.customer_id)
        seller_key = seller_map.get(row.seller_id)
        order_key = order_map.get(row.order_id)
        purchase_date = row.order_purchase_timestamp
        order_date_key = date_map.get(purchase_date.date()) if pd.notnull(purchase_date) else None

        if None in (product_key, customer_key, seller_key, order_key, order_date_key):
            skipped += 1
            continue

        data.append((
            row.order_id,
            int(row.order_item_id),
            product_key,
            customer_key,
            seller_key,
            order_date_key,
            order_key,
            float(row.price),
            float(row.freight_value),
        ))

    if skipped:
        logging.warning(f"Skipped {skipped} order_item rows with unresolved dimension keys.")

    insert_batches(cur, """
        INSERT INTO public.fact_order_items
            (order_id, order_item_id, product_key, customer_key, seller_key,
             order_date_key, order_key, price, freight_value)
        VALUES %s
        ON CONFLICT (order_id, order_item_id) DO NOTHING
    """, data, table_name="fact_order_items")


def load_fact_reviews(cur, reviews, order_map):
    # Drop only true full-row duplicates. review_id is NOT globally unique — Olist
    # reuses review_id values across unrelated orders, so the natural key is
    # (review_id, order_id), not review_id alone.
    reviews = reviews.drop_duplicates()

    data = []
    skipped = 0
    for row in reviews.itertuples(index=False):
        order_key = order_map.get(row.order_id)
        if order_key is None:
            skipped += 1
            continue
        data.append((
            row.review_id,
            row.order_id,
            order_key,
            int(row.review_score),
        ))

    if skipped:
        logging.warning(f"Skipped {skipped} review rows with unresolved order_key.")

    insert_batches(cur, """
        INSERT INTO public.fact_reviews (review_id, order_id, order_key, review_score)
        VALUES %s
        ON CONFLICT (review_id, order_id) DO NOTHING
    """, data, table_name="fact_reviews")


def load_fact_payments(cur, payments, order_map):
    data = []
    skipped = 0
    for row in payments.itertuples(index=False):
        order_key = order_map.get(row.order_id)
        if order_key is None:
            skipped += 1
            continue
        data.append((
            row.order_id,
            int(row.payment_sequential),
            order_key,
            to_native(row.payment_type),
            to_int(row.payment_installments),
            float(row.payment_value),
        ))

    if skipped:
        logging.warning(f"Skipped {skipped} payment rows with unresolved order_key.")

    insert_batches(cur, """
        INSERT INTO public.fact_payments
            (order_id, payment_sequential, order_key, payment_type, payment_installments, payment_value)
        VALUES %s
        ON CONFLICT (order_id, payment_sequential) DO NOTHING
    """, data, table_name="fact_payments")


def run_etl():
    logging.info("Starting Olist ETL process...")

    orders, order_items, customers, products, sellers, payments, reviews, category_translation = load_csvs()

    conn = get_connection()
    cur = conn.cursor()

    try:
        # 1. Dimensions first
        load_dim_customer(cur, customers)
        load_dim_product(cur, products, category_translation)
        load_dim_seller(cur, sellers)
        load_dim_date(cur, orders)
        load_dim_order(cur, orders)

        # 2. Read back surrogate keys
        product_map, customer_map, seller_map, date_map, order_map = fetch_key_maps(cur)

        # 3. Facts
        load_fact_order_items(cur, order_items, orders, product_map, customer_map, seller_map, date_map, order_map)
        load_fact_reviews(cur, reviews, order_map)
        load_fact_payments(cur, payments, order_map)

        conn.commit()
        logging.info("Olist ETL process completed successfully.")

    except Exception as e:
        conn.rollback()
        logging.error(f"An error occurred: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run_etl()
