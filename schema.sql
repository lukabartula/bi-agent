-- ============================================================
-- DIMENSIONS
-- ============================================================

CREATE TABLE dim_customer (
    customer_key              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id               VARCHAR(32)  NOT NULL,
    customer_unique_id        VARCHAR(32)  NOT NULL,
    customer_zip_code_prefix  VARCHAR(5),
    customer_city             VARCHAR(100),
    customer_state            CHAR(2),
    CONSTRAINT uq_dim_customer_customer_id UNIQUE (customer_id)
);

CREATE TABLE dim_product (
    product_key                    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id                     VARCHAR(32) NOT NULL,
    product_category_name          VARCHAR(100),
    product_category_name_english  VARCHAR(100),
    product_name_length            INTEGER,   -- source: product_name_lenght
    product_description_length     INTEGER,   -- source: product_description_lenght
    product_photos_qty             INTEGER,
    product_weight_g               INTEGER,
    product_length_cm              INTEGER,
    product_height_cm              INTEGER,
    product_width_cm               INTEGER,
    CONSTRAINT uq_dim_product_product_id UNIQUE (product_id)
);

CREATE TABLE dim_seller (
    seller_key              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    seller_id               VARCHAR(32) NOT NULL,
    seller_zip_code_prefix  VARCHAR(5),
    seller_city             VARCHAR(100),
    seller_state            CHAR(2),
    CONSTRAINT uq_dim_seller_seller_id UNIQUE (seller_id)
);

CREATE TABLE dim_date (
    date_key      INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_date     DATE NOT NULL,
    year          INTEGER NOT NULL,
    quarter       INTEGER NOT NULL,
    month         INTEGER NOT NULL,
    day           INTEGER NOT NULL,
    day_of_week   INTEGER NOT NULL,   -- pandas .dayofweek convention: 0=Monday .. 6=Sunday (NOT Postgres EXTRACT(DOW))
    week          INTEGER NOT NULL,
    CONSTRAINT uq_dim_date_full_date UNIQUE (full_date)
);

CREATE TABLE dim_order (
    order_key                       INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id                        VARCHAR(32) NOT NULL,
    order_status                    VARCHAR(20),
    order_purchase_timestamp        TIMESTAMP,
    order_approved_at               TIMESTAMP,
    order_delivered_carrier_date    TIMESTAMP,
    order_delivered_customer_date   TIMESTAMP,
    order_estimated_delivery_date   TIMESTAMP,
    delivery_days                   INTEGER,  -- delivered_customer_date - purchase_timestamp; NULL if undelivered
    delivery_delay_days             INTEGER,  -- delivered_customer_date - estimated_delivery_date; negative = early; NULL if undelivered
    CONSTRAINT uq_dim_order_order_id UNIQUE (order_id)
);

-- ============================================================
-- FACTS (constellation: three facts sharing dim_order / other dims)
-- ============================================================

CREATE TABLE fact_order_items (
    order_item_key      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id            VARCHAR(32) NOT NULL,   -- degenerate dim
    order_item_id       INTEGER     NOT NULL,   -- degenerate dim
    product_key         INTEGER NOT NULL,
    customer_key        INTEGER NOT NULL,       -- denormalized via orders (two-hop join at ETL time)
    seller_key          INTEGER NOT NULL,
    order_date_key      INTEGER NOT NULL,       -- from order_purchase_timestamp date part
    order_key           INTEGER NOT NULL,
    price               NUMERIC(10,2) NOT NULL,
    freight_value       NUMERIC(10,2) NOT NULL,
    total_item_value    NUMERIC(10,2) GENERATED ALWAYS AS (price + freight_value) STORED,

    CONSTRAINT uq_fact_order_items_natural UNIQUE (order_id, order_item_id),
    CONSTRAINT fk_foi_product     FOREIGN KEY (product_key)    REFERENCES dim_product (product_key),
    CONSTRAINT fk_foi_customer    FOREIGN KEY (customer_key)   REFERENCES dim_customer (customer_key),
    CONSTRAINT fk_foi_seller      FOREIGN KEY (seller_key)     REFERENCES dim_seller (seller_key),
    CONSTRAINT fk_foi_order_date  FOREIGN KEY (order_date_key) REFERENCES dim_date (date_key),
    CONSTRAINT fk_foi_order       FOREIGN KEY (order_key)      REFERENCES dim_order (order_key)
);

CREATE TABLE fact_reviews (
    review_key      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    review_id       VARCHAR(32) NOT NULL,
    order_id        VARCHAR(32) NOT NULL,  -- degenerate dim; part of natural key alongside review_id
    order_key       INTEGER NOT NULL,
    review_score    SMALLINT NOT NULL,

    CONSTRAINT uq_fact_reviews_natural UNIQUE (review_id, order_id),
    CONSTRAINT fk_fr_order FOREIGN KEY (order_key) REFERENCES dim_order (order_key)
);
-- Natural key is (review_id, order_id), NOT review_id alone: Olist reuses review_id values
-- across unrelated orders (789 review_ids each appear on 2-3 rows, every one against a
-- different order_id). Drop only true full-row duplicates before insert.

CREATE TABLE fact_payments (
    payment_key           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id              VARCHAR(32)  NOT NULL,  -- degenerate dim
    payment_sequential    INTEGER      NOT NULL,  -- degenerate dim
    order_key             INTEGER NOT NULL,
    payment_type          VARCHAR(20),
    payment_installments  INTEGER,
    payment_value         NUMERIC(10,2),

    CONSTRAINT uq_fact_payments_natural UNIQUE (order_id, payment_sequential),
    CONSTRAINT fk_fp_order FOREIGN KEY (order_key) REFERENCES dim_order (order_key)
);
