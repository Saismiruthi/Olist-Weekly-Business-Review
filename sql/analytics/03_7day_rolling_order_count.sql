WITH daily AS (
  SELECT purchase_ts::date AS order_date, COUNT(DISTINCT order_id) AS order_count
  FROM stg_orders
  WHERE purchase_ts IS NOT NULL
  GROUP BY purchase_ts::date
),
calendar AS (
  SELECT generate_series((SELECT MIN(order_date) FROM daily),
                         (SELECT MAX(order_date) FROM daily),
                         interval '1 day')::date AS order_date
),
filled AS (
  SELECT c.order_date, COALESCE(d.order_count, 0) AS order_count
  FROM calendar c LEFT JOIN daily d USING (order_date)
)
SELECT order_date, order_count,
       ROUND(AVG(order_count) OVER (
         ORDER BY order_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
       ), 2) AS rolling_7day_avg
FROM filled
ORDER BY order_date;
