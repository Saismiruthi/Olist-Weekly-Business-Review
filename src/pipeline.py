"""Idempotent Olist ELT pipeline: raw CSVs -> staging views -> order mart."""

import logging
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("pipeline.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("olist_pipeline")

DATA_DIR = Path(os.getenv("DATA_DIR", "data/raw"))
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is missing. Copy .env.example to .env "
        "and configure PostgreSQL."
    )

FILES = {
    "orders": (
        "olist_orders_dataset.csv",
        [
            "order_id", "customer_id", "order_status",
            "order_purchase_timestamp", "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
    ),
    "order_items": (
        "olist_order_items_dataset.csv",
        [
            "order_id", "order_item_id", "product_id",
            "seller_id", "price", "freight_value",
        ],
    ),
    "payments": (
        "olist_order_payments_dataset.csv",
        [
            "order_id", "payment_sequential", "payment_type",
            "payment_installments", "payment_value",
        ],
    ),
    "reviews": (
        "olist_order_reviews_dataset.csv",
        ["review_id", "order_id", "review_score"],
    ),
    "customers": (
        "olist_customers_dataset.csv",
        ["customer_id", "customer_unique_id", "customer_state"],
    ),
    "products": (
        "olist_products_dataset.csv",
        ["product_id", "product_category_name"],
    ),
}


def require_file_and_columns(path: Path, required: list[str]) -> pd.DataFrame:
    """Fail clearly if a required CSV or required column is missing."""
    if not path.exists():
        raise FileNotFoundError(
            f"Required dataset file not found: {path}"
        )

    df = pd.read_csv(path)
    missing = sorted(set(required) - set(df.columns))

    if missing:
        raise ValueError(
            f"{path.name} is missing required columns: {missing}"
        )

    return df


def drop_dependent_objects(engine) -> None:
    """Remove the old mart and staging views before replacing raw tables."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS mart_order_summary"))

        for view in [
            "stg_order_items",
            "stg_payments",
            "stg_reviews",
            "stg_customers",
            "stg_products",
            "stg_orders",
        ]:
            conn.execute(text(f"DROP VIEW IF EXISTS {view} CASCADE"))


def load_raw_tables(engine) -> None:
    """Load source CSVs into PostgreSQL raw tables."""
    for name, (filename, required) in FILES.items():
        path = DATA_DIR / filename
        log.info("Reading %s", filename)

        df = require_file_and_columns(path, required)

        df.to_sql(
            f"raw_{name}",
            engine,
            if_exists="replace",
            index=False,
            chunksize=5000,
            method="multi",
        )

        log.info("Loaded raw_%s: %s rows", name, len(df))


def build_staging_and_mart(engine) -> None:
    """Build typed staging views and a mart with one row per order."""
    with engine.begin() as conn:
        log.info("Creating staging views")

        conn.execute(text("""
            CREATE VIEW stg_orders AS
            SELECT
                order_id,
                customer_id,
                order_status,
                NULLIF(order_purchase_timestamp, '')::timestamp AS purchase_ts,
                NULLIF(order_delivered_customer_date, '')::timestamp
                    AS delivered_ts,
                NULLIF(order_estimated_delivery_date, '')::timestamp
                    AS estimated_delivery_ts
            FROM raw_orders
        """))

        conn.execute(text("""
            CREATE VIEW stg_order_items AS
            SELECT
                order_id,
                order_item_id,
                product_id,
                seller_id,
                CAST(price AS numeric(12,2)) AS price,
                CAST(freight_value AS numeric(12,2)) AS freight_value
            FROM raw_order_items
        """))

        conn.execute(text("""
            CREATE VIEW stg_payments AS
            SELECT
                order_id,
                payment_sequential,
                payment_type,
                CAST(payment_installments AS integer)
                    AS payment_installments,
                CAST(payment_value AS numeric(12,2)) AS payment_value
            FROM raw_payments
        """))

        conn.execute(text("""
            CREATE VIEW stg_reviews AS
            SELECT
                review_id,
                order_id,
                CAST(review_score AS integer) AS review_score
            FROM raw_reviews
        """))

        conn.execute(text("""
            CREATE VIEW stg_customers AS
            SELECT customer_id, customer_unique_id, customer_state
            FROM raw_customers
        """))

        conn.execute(text("""
            CREATE VIEW stg_products AS
            SELECT
                product_id,
                COALESCE(
                    NULLIF(product_category_name, ''),
                    'unknown'
                ) AS product_category_name
            FROM raw_products
        """))

        log.info("Building mart_order_summary")

        conn.execute(text("""
            CREATE TABLE mart_order_summary AS
            WITH item_totals AS (
                SELECT
                    order_id,
                    SUM(price) AS item_total,
                    SUM(freight_value) AS freight_total,
                    COUNT(*) AS item_count
                FROM stg_order_items
                GROUP BY order_id
            ),
            payment_totals AS (
                SELECT
                    order_id,
                    SUM(payment_value) AS payment_total
                FROM stg_payments
                GROUP BY order_id
            ),
            review_scores AS (
                SELECT
                    order_id,
                    AVG(review_score)::numeric(4,2) AS review_score,
                    COUNT(*) AS review_count
                FROM stg_reviews
                GROUP BY order_id
            )
            SELECT
                o.order_id,
                o.customer_id,
                c.customer_unique_id,
                c.customer_state,
                o.order_status,
                o.purchase_ts,
                o.delivered_ts,
                o.estimated_delivery_ts,
                COALESCE(i.item_total, 0)::numeric(12,2)
                    AS item_total,
                COALESCE(i.freight_total, 0)::numeric(12,2)
                    AS freight_total,
                (
                    COALESCE(i.item_total, 0)
                    + COALESCE(i.freight_total, 0)
                )::numeric(12,2) AS item_plus_freight,
                COALESCE(p.payment_total, 0)::numeric(12,2)
                    AS payment_total,
                COALESCE(i.item_count, 0) AS item_count,
                r.review_score,
                COALESCE(r.review_count, 0) AS review_count,
                CASE
                    WHEN o.delivered_ts IS NOT NULL
                     AND o.estimated_delivery_ts IS NOT NULL
                    THEN (
                        o.delivered_ts::date
                        - o.estimated_delivery_ts::date
                    )
                    ELSE NULL
                END AS delivery_delay_days
            FROM stg_orders o
            LEFT JOIN item_totals i ON o.order_id = i.order_id
            LEFT JOIN payment_totals p ON o.order_id = p.order_id
            LEFT JOIN review_scores r ON o.order_id = r.order_id
            LEFT JOIN stg_customers c ON o.customer_id = c.customer_id
        """))

        conn.execute(text("""
            CREATE UNIQUE INDEX ux_mart_order_summary_order_id
            ON mart_order_summary(order_id)
        """))

        log.info("Mart built successfully")


def run() -> None:
    """Execute the full pipeline."""
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    try:
        log.info(
            "Starting Olist pipeline. Input directory: %s",
            DATA_DIR.resolve(),
        )

        # Validate every file before modifying the database.
        for filename, required in FILES.values():
            require_file_and_columns(DATA_DIR / filename, required)

        # Views must be dropped before pandas replaces their source tables.
        drop_dependent_objects(engine)

        load_raw_tables(engine)
        build_staging_and_mart(engine)

        from quality_checks import run_checks

        run_checks(engine)
        log.info("Pipeline completed successfully.")

    except Exception:
        log.exception("Olist pipeline failed.")
        raise

    finally:
        engine.dispose()


if __name__ == "__main__":
    run()
