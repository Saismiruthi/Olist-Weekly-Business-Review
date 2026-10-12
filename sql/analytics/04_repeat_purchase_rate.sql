-- Important: customer_unique_id identifies a person across multiple order-specific customer_id values.
WITH customer_orders AS (
  SELECT c.customer_unique_id, COUNT(DISTINCT o.order_id) AS order_count
  FROM stg_orders o
  JOIN stg_customers c ON c.customer_id = o.customer_id
  WHERE o.order_status <> 'canceled'
  GROUP BY c.customer_unique_id
)
SELECT COUNT(*) AS unique_customers,
       COUNT(*) FILTER (WHERE order_count >= 2) AS repeat_customers,
       ROUND(100.0 * COUNT(*) FILTER (WHERE order_count >= 2) /
             NULLIF(COUNT(*), 0), 2) AS repeat_purchase_rate_pct
FROM customer_orders;
