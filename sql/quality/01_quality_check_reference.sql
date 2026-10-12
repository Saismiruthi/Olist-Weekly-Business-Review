-- Run against PostgreSQL after pipeline creation.
-- The executable checks are also defined in src/quality_checks.py.
SELECT 'null_order_id' AS check_name, COUNT(*) AS failing_rows
FROM raw_orders WHERE order_id IS NULL OR BTRIM(order_id) = ''
UNION ALL
SELECT 'duplicate_order_id', COUNT(*) FROM (
  SELECT order_id FROM raw_orders GROUP BY order_id HAVING COUNT(*) > 1
) d
UNION ALL
SELECT 'delivery_before_purchase', COUNT(*) FROM stg_orders
WHERE delivered_ts < purchase_ts
UNION ALL
SELECT 'payment_mismatch_over_0_05', COUNT(*) FROM mart_order_summary
WHERE payment_total > 0 AND ABS(payment_total - item_plus_freight) > 0.05
UNION ALL
SELECT 'orders_without_customer', COUNT(*) FROM stg_orders o
LEFT JOIN stg_customers c ON o.customer_id = c.customer_id
WHERE c.customer_id IS NULL
UNION ALL
SELECT 'invalid_review_score', COUNT(*) FROM stg_reviews
WHERE review_score NOT BETWEEN 1 AND 5
UNION ALL
SELECT 'delivered_without_delivery_timestamp', COUNT(*) FROM stg_orders
WHERE order_status = 'delivered' AND delivered_ts IS NULL;
