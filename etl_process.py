import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def get_connection():
    """Establishes a connection to the PostgreSQL database."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DATABASE"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
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

def run_etl():
    logging.info("Starting ETL process...")
    
    # 1. Load Source Data
    # Encoding ISO-8859-1 is common for this dataset
    df = pd.read_csv('OnlineRetail.csv', encoding='ISO-8859-1')
    
    # 2. Deduplication & Cleaning
    df = df.drop_duplicates()
    df['InvoiceDate'] = pd.to_datetime(df['InvoiceDate'])
    df['CustomerID'] = df['CustomerID'].astype(str).replace('nan', None)
    df['Description'] = df['Description'].str.strip()
    
    conn = get_connection()
    cur = conn.cursor()
    
    try:
        # 3. Populate Dimension: dim_product
        products = df[['StockCode', 'Description']].drop_duplicates().dropna(subset=['StockCode'])
        insert_batches(cur, """
            INSERT INTO public.dim_product (stock_code, description)
            VALUES %s
            ON CONFLICT (stock_code) DO NOTHING
        """, products.values.tolist(), table_name="dim_product")
        
        # 4. Populate Dimension: dim_customer
        customers = df[['CustomerID', 'Country']].drop_duplicates().dropna(subset=['CustomerID'])
        insert_batches(cur, """
            INSERT INTO public.dim_customer (customer_id, country)
            VALUES %s
            ON CONFLICT (customer_id) DO NOTHING
        """, customers.values.tolist(), table_name="dim_customer")
        
        # 5. Populate Dimension: dim_date
        dates = df[['InvoiceDate']].drop_duplicates()
        date_data = [(
            d, d.year, d.month, d.day, d.quarter, d.dayofweek, d.hour
        ) for d in dates['InvoiceDate']]
        insert_batches(cur, """
            INSERT INTO public.dim_date (full_date, year, month, day, quarter, day_of_week, hour)
            VALUES %s
            ON CONFLICT (full_date) DO NOTHING
        """, date_data, table_name="dim_date")
        
        # 6. Prepare and Populate Fact: fact_sales
        # Fetch surrogate keys to map business keys to IDs
        cur.execute("SELECT product_key, stock_code FROM public.dim_product")
        prod_map = {row[1]: row[0] for row in cur.fetchall()}
        
        cur.execute("SELECT customer_key, customer_id FROM public.dim_customer")
        cust_map = {row[1]: row[0] for row in cur.fetchall()}
        
        cur.execute("SELECT date_key, full_date FROM public.dim_date")
        date_map = {row[1]: row[0] for row in cur.fetchall()}
        
        # Map keys and calculate total amount
        df['product_key'] = df['StockCode'].map(prod_map)
        df['customer_key'] = df['CustomerID'].map(cust_map)
        df['date_key'] = df['InvoiceDate'].map(date_map)
        df['total_amount'] = df['Quantity'] * df['UnitPrice']
        
        # Prepare fact table data
        fact_df = df[['InvoiceNo', 'product_key', 'customer_key', 'date_key', 'Quantity', 'UnitPrice', 'total_amount']].copy()
        fact_df = fact_df.dropna(subset=['product_key', 'date_key'])
        
        # Convert to standard Python types to avoid numpy type issues
        fact_data = []
        for row in fact_df.itertuples(index=False):
            fact_data.append((
                str(row.InvoiceNo),
                int(row.product_key),
                int(row.customer_key) if pd.notnull(row.customer_key) else None,
                int(row.date_key),
                int(row.Quantity),
                float(row.UnitPrice),
                float(row.total_amount)
            ))
        
        logging.info(f"Total rows to insert into fact_sales: {len(fact_data)}")
        
        insert_batches(cur, """
            INSERT INTO public.fact_sales (invoice_no, product_key, customer_key, date_key, quantity, unit_price, total_amount)
            VALUES %s
            ON CONFLICT ON CONSTRAINT unique_sale DO NOTHING
        """, fact_data, table_name="fact_sales")
        
        conn.commit()
        logging.info("ETL process completed successfully.")
        
    except Exception as e:
        conn.rollback()
        logging.error(f"An error occurred: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run_etl()
