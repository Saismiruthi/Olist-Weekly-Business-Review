-- Revenue is defined as total payment value for orders purchased in the month.
WITH monthly AS (
  SELECT DATE_TRUNC('month', purchase_ts)::date AS month,
         SUM(payment_total) AS revenue
  FROM mart_order_summary
  WHERE purchase_ts IS NOT NULL
  GROUP BY 1
),
with_previous AS (
  SELECT month, revenue,
         LAG(revenue) OVER (ORDER BY month) AS previous_month_revenue
  FROM monthly
)
SELECT month, revenue, previous_month_revenue,
       ROUND(100.0 * (revenue - previous_month_revenue) /
             NULLIF(previous_month_revenue, 0), 2) AS growth_pct
FROM with_previous
ORDER BY month;
