-- Category revenue is item price (excluding freight), attributed to the customer's state.
WITH category_revenue AS (
  SELECT c.customer_state AS state,
         COALESCE(p.product_category_name, 'unknown') AS category,
         SUM(oi.price) AS revenue
  FROM stg_order_items oi
  JOIN stg_orders o ON o.order_id = oi.order_id
  JOIN stg_customers c ON c.customer_id = o.customer_id
  JOIN stg_products p ON p.product_id = oi.product_id
  WHERE o.order_status <> 'canceled'
  GROUP BY c.customer_state, COALESCE(p.product_category_name, 'unknown')
),
ranked AS (
  SELECT state, category, revenue,
         DENSE_RANK() OVER (PARTITION BY state ORDER BY revenue DESC) AS category_rank
  FROM category_revenue
)
SELECT state, category, revenue, category_rank
FROM ranked
WHERE category_rank <= 3
ORDER BY state, category_rank, category;
