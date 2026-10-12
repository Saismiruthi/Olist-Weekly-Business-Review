"""SQL-based data quality checks with blocking and non-blocking exceptions."""

import logging
from sqlalchemy import text

log = logging.getLogger("olist_pipeline")

# These checks stop the pipeline when they fail.
BLOCKING_CHECKS = [
    (
        "Q1 null order_id",
        """SELECT COUNT(*) FROM raw_orders
           WHERE order_id IS NULL OR BTRIM(order_id) = ''""",
    ),
    (
        "Q2 duplicate order_id",
        """SELECT COUNT(*) FROM (
               SELECT order_id
               FROM raw_orders
               GROUP BY order_id
               HAVING COUNT(*) > 1
           ) x""",
    ),
    (
        "Q3 delivery before purchase",
        """SELECT COUNT(*) FROM stg_orders
           WHERE delivered_ts IS NOT NULL
             AND purchase_ts IS NOT NULL
             AND delivered_ts < purchase_ts""",
    ),
    (
        "Q4 orders without customer",
        """SELECT COUNT(*) FROM stg_orders o
           LEFT JOIN stg_customers c
             ON o.customer_id = c.customer_id
           WHERE c.customer_id IS NULL""",
    ),
    (
        "Q5 invalid review score",
        """SELECT COUNT(*) FROM stg_reviews
           WHERE review_score IS NOT NULL
             AND review_score NOT BETWEEN 1 AND 5""",
    ),
]

# These source-data exceptions are logged but do not stop the pipeline.
WARNING_CHECKS = [
    (
        "W1 payment mismatch over R$0.05 for orders with items",
        """SELECT COUNT(*) FROM mart_order_summary m
           WHERE m.payment_total > 0
             AND ABS(m.payment_total - m.item_plus_freight) > 0.05
             AND EXISTS (
                 SELECT 1 FROM raw_order_items i
                 WHERE i.order_id = m.order_id
             )""",
    ),
    (
        "W2 orders with payments but no item records",
        """SELECT COUNT(*) FROM mart_order_summary m
           WHERE m.payment_total > 0
             AND NOT EXISTS (
                 SELECT 1 FROM raw_order_items i
                 WHERE i.order_id = m.order_id
             )""",
    ),
    (
        "W3 delivered orders missing delivery timestamp",
        """SELECT COUNT(*) FROM stg_orders
           WHERE order_status = 'delivered'
             AND delivered_ts IS NULL""",
    ),
]


def run_checks(engine):
    failures = []

    with engine.connect() as conn:
        for name, sql in BLOCKING_CHECKS:
            count = conn.execute(text(sql)).scalar_one()
            log.info(
                "DATA QUALITY | BLOCKING | %s | failing_rows=%s",
                name,
                count,
            )
            if count > 0:
                failures.append((name, count))

        for name, sql in WARNING_CHECKS:
            count = conn.execute(text(sql)).scalar_one()
            log.warning(
                "DATA QUALITY | WARNING | %s | exception_rows=%s",
                name,
                count,
            )

    if failures:
        details = "; ".join(
            f"{name}: {count} rows" for name, count in failures
        )
        raise RuntimeError(
            "DATA QUALITY ALARM - pipeline stopped. " + details
        )

    log.info("All blocking data quality checks passed.")
