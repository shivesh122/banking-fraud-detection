-- Banking Fraud Detection: star schema (SQLite edition, loaded by the pipeline)
DROP VIEW IF EXISTS vw_daily_fraud;
DROP VIEW IF EXISTS vw_alert_queue;
DROP VIEW IF EXISTS vw_customer_risk;
DROP TABLE IF EXISTS fact_transactions;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_merchant;
DROP TABLE IF EXISTS dim_date;

CREATE TABLE dim_date (
    date_key    INTEGER PRIMARY KEY,   -- yyyymmdd
    full_date   TEXT NOT NULL,
    year        INTEGER NOT NULL,
    month       INTEGER NOT NULL,
    year_month  TEXT NOT NULL,
    week_start  TEXT NOT NULL,
    day_of_week TEXT NOT NULL,
    is_weekend  INTEGER NOT NULL
);

CREATE TABLE dim_customer (
    customer_key      INTEGER PRIMARY KEY,
    customer_id       TEXT NOT NULL UNIQUE,
    segment           TEXT NOT NULL,
    home_city         TEXT NOT NULL,
    account_open_date TEXT NOT NULL
);

CREATE TABLE dim_merchant (
    merchant_key  INTEGER PRIMARY KEY,
    merchant_id   TEXT NOT NULL UNIQUE,
    category      TEXT NOT NULL,
    merchant_city TEXT NOT NULL,
    is_high_risk  INTEGER NOT NULL
);

CREATE TABLE fact_transactions (
    txn_id            TEXT PRIMARY KEY,
    date_key          INTEGER NOT NULL REFERENCES dim_date(date_key),
    txn_time          TEXT NOT NULL,
    hour              INTEGER NOT NULL,
    customer_key      INTEGER NOT NULL REFERENCES dim_customer(customer_key),
    merchant_key      INTEGER NOT NULL REFERENCES dim_merchant(merchant_key),
    channel           TEXT NOT NULL,
    txn_city          TEXT NOT NULL,
    amount            REAL NOT NULL,
    amount_ratio      REAL NOT NULL,
    txn_count_1h      INTEGER NOT NULL,
    distance_home_km  REAL NOT NULL,
    is_new_device     INTEGER NOT NULL,
    anomaly_score     REAL NOT NULL,
    fraud_probability REAL NOT NULL,
    is_alert          INTEGER NOT NULL,
    is_fraud          INTEGER NOT NULL,   -- confirmed label (chargeback / investigation)
    fraud_type        TEXT,
    dataset           TEXT NOT NULL CHECK (dataset IN ('warmup', 'train', 'test'))
);

CREATE INDEX ix_tx_date     ON fact_transactions(date_key);
CREATE INDEX ix_tx_customer ON fact_transactions(customer_key, txn_time);
CREATE INDEX ix_tx_alert    ON fact_transactions(is_alert, fraud_probability);

CREATE VIEW vw_daily_fraud AS
SELECT d.full_date,
       COUNT(*)                                      AS transactions,
       SUM(f.amount)                                 AS amount,
       SUM(f.is_fraud)                               AS frauds,
       SUM(CASE WHEN f.is_fraud = 1 THEN f.amount END) AS fraud_amount,
       SUM(f.is_alert)                               AS alerts,
       SUM(f.is_alert * f.is_fraud)                  AS true_alerts,
       SUM(CASE WHEN f.is_alert = 1 AND f.is_fraud = 1 THEN f.amount ELSE 0 END) AS fraud_amount_caught
FROM fact_transactions f JOIN dim_date d ON d.date_key = f.date_key
GROUP BY d.full_date;

CREATE VIEW vw_alert_queue AS
SELECT f.txn_id, f.txn_time, c.customer_id, c.segment, c.home_city, m.merchant_id, m.category,
       f.channel, f.txn_city, f.amount, f.fraud_probability, f.anomaly_score, f.is_fraud, f.fraud_type
FROM fact_transactions f
JOIN dim_customer c ON c.customer_key = f.customer_key
JOIN dim_merchant m ON m.merchant_key = f.merchant_key
WHERE f.is_alert = 1;

CREATE VIEW vw_customer_risk AS
SELECT c.customer_id, c.segment, c.home_city,
       COUNT(*) AS transactions, SUM(f.is_alert) AS alerts, SUM(f.is_fraud) AS confirmed_frauds,
       MAX(f.fraud_probability) AS max_probability
FROM fact_transactions f JOIN dim_customer c ON c.customer_key = f.customer_key
GROUP BY c.customer_id, c.segment, c.home_city;
