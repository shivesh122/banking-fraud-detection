-- Example analysis queries (SQLite: data/warehouse/fraud.db)

-- 1. Model performance on the held-out test period
SELECT COUNT(*)                                         AS transactions,
       SUM(is_fraud)                                    AS frauds,
       SUM(is_alert)                                    AS alerts,
       SUM(is_alert * is_fraud)                         AS true_alerts,
       ROUND(1.0 * SUM(is_alert * is_fraud) / SUM(is_alert), 3) AS precision,
       ROUND(1.0 * SUM(is_alert * is_fraud) / SUM(is_fraud), 3) AS recall
FROM fact_transactions
WHERE dataset = 'test';

-- 2. Fraud rate and detection by channel (test period)
SELECT channel,
       COUNT(*) AS transactions,
       ROUND(100.0 * SUM(is_fraud) / COUNT(*), 3) AS fraud_rate_pct,
       ROUND(1.0 * SUM(is_alert * is_fraud) / NULLIF(SUM(is_fraud), 0), 3) AS recall
FROM fact_transactions
WHERE dataset = 'test'
GROUP BY channel
ORDER BY fraud_rate_pct DESC;

-- 3. Riskiest merchant categories by fraud amount
SELECT m.category,
       SUM(f.is_fraud) AS frauds,
       ROUND(SUM(CASE WHEN f.is_fraud = 1 THEN f.amount ELSE 0 END), 0) AS fraud_amount,
       ROUND(100.0 * SUM(f.is_fraud) / COUNT(*), 3) AS fraud_rate_pct
FROM fact_transactions f JOIN dim_merchant m ON m.merchant_key = f.merchant_key
GROUP BY m.category
ORDER BY fraud_amount DESC;

-- 4. Velocity check: customers with 4+ transactions inside any 60-minute window (window function)
WITH ordered AS (
    SELECT customer_key, txn_time,
           LAG(txn_time, 3) OVER (PARTITION BY customer_key ORDER BY txn_time) AS t_minus_3
    FROM fact_transactions
)
SELECT c.customer_id, COUNT(*) AS bursts
FROM ordered o JOIN dim_customer c ON c.customer_key = o.customer_key
WHERE o.t_minus_3 IS NOT NULL
  AND (julianday(o.txn_time) - julianday(o.t_minus_3)) * 24 * 60 <= 60
GROUP BY c.customer_id
ORDER BY bursts DESC
LIMIT 10;

-- 5. Today's top alerts for the analyst queue
SELECT txn_id, txn_time, customer_id, category, channel, txn_city, amount, ROUND(fraud_probability, 3) AS p
FROM vw_alert_queue
ORDER BY txn_time DESC, fraud_probability DESC
LIMIT 20;
