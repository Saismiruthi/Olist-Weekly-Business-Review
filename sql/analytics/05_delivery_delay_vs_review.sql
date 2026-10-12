WITH order_level AS (
  SELECT order_id, delivery_delay_days, review_score
  FROM mart_order_summary
  WHERE delivered_ts IS NOT NULL
    AND estimated_delivery_ts IS NOT NULL
    AND review_score IS NOT NULL
)
SELECT CASE
         WHEN delivery_delay_days < 0 THEN 'Early'
         WHEN delivery_delay_days = 0 THEN 'On time'
         ELSE 'Late'
       END AS delivery_performance,
       COUNT(*) AS orders,
       ROUND(AVG(delivery_delay_days)::numeric, 2) AS avg_delay_days,
       ROUND(AVG(review_score)::numeric, 2) AS avg_review_score
FROM order_level
GROUP BY 1
ORDER BY CASE
  WHEN CASE WHEN delivery_delay_days < 0 THEN 'Early'
            WHEN delivery_delay_days = 0 THEN 'On time'
            ELSE 'Late' END = 'Early' THEN 1
  WHEN CASE WHEN delivery_delay_days = 0 THEN 'On time' ELSE 'Late' END = 'On time' THEN 2
  ELSE 3 END;
