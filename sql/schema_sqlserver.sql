/* Banking Fraud Detection: star schema for Microsoft SQL Server.
   Performance features for large transaction volumes:
     - monthly partitioning of the fact table (fast loads, partition switching, incremental refresh)
     - clustered columnstore index (high compression, fast aggregations for Power BI DirectQuery/Import)
     - narrow rowstore index for the analyst alert queue                                              */

IF DB_ID('FraudDW') IS NULL CREATE DATABASE FraudDW;
GO
USE FraudDW;
GO

DROP VIEW  IF EXISTS dbo.vw_daily_fraud, dbo.vw_alert_queue;
DROP TABLE IF EXISTS dbo.fact_transactions, dbo.dim_customer, dbo.dim_merchant, dbo.dim_date;
IF EXISTS (SELECT 1 FROM sys.partition_schemes WHERE name = 'ps_month') DROP PARTITION SCHEME ps_month;
IF EXISTS (SELECT 1 FROM sys.partition_functions WHERE name = 'pf_month') DROP PARTITION FUNCTION pf_month;
GO

CREATE PARTITION FUNCTION pf_month (INT)
AS RANGE RIGHT FOR VALUES (20260401, 20260501, 20260601, 20260701, 20260801, 20260901, 20261001, 20261101, 20261201);
CREATE PARTITION SCHEME ps_month AS PARTITION pf_month ALL TO ([PRIMARY]);
GO

CREATE TABLE dbo.dim_date (
    date_key    INT         NOT NULL PRIMARY KEY,
    full_date   DATE        NOT NULL,
    [year]      SMALLINT    NOT NULL,
    [month]     TINYINT     NOT NULL,
    year_month  CHAR(7)     NOT NULL,
    week_start  DATE        NOT NULL,
    day_of_week VARCHAR(10) NOT NULL,
    is_weekend  BIT         NOT NULL
);

CREATE TABLE dbo.dim_customer (
    customer_key      INT         NOT NULL PRIMARY KEY,
    customer_id       VARCHAR(10) NOT NULL UNIQUE,
    segment           VARCHAR(20) NOT NULL,
    home_city         VARCHAR(40) NOT NULL,
    account_open_date DATE        NOT NULL
);

CREATE TABLE dbo.dim_merchant (
    merchant_key  INT         NOT NULL PRIMARY KEY,
    merchant_id   VARCHAR(10) NOT NULL UNIQUE,
    category      VARCHAR(40) NOT NULL,
    merchant_city VARCHAR(40) NOT NULL,
    is_high_risk  BIT         NOT NULL
);

CREATE TABLE dbo.fact_transactions (
    txn_id            VARCHAR(12)    NOT NULL,
    date_key          INT            NOT NULL,
    txn_time          DATETIME2(0)   NOT NULL,
    [hour]            TINYINT        NOT NULL,
    customer_key      INT            NOT NULL,
    merchant_key      INT            NOT NULL,
    channel           VARCHAR(10)    NOT NULL,
    txn_city          VARCHAR(40)    NOT NULL,
    amount            DECIMAL(14, 2) NOT NULL,
    amount_ratio      REAL           NOT NULL,
    txn_count_1h      SMALLINT       NOT NULL,
    distance_home_km  REAL           NOT NULL,
    is_new_device     BIT            NOT NULL,
    anomaly_score     REAL           NOT NULL,
    fraud_probability REAL           NOT NULL,
    is_alert          BIT            NOT NULL,
    is_fraud          BIT            NOT NULL,
    fraud_type        VARCHAR(30)    NULL,
    dataset           VARCHAR(10)    NOT NULL
) ON ps_month (date_key);
GO

CREATE CLUSTERED COLUMNSTORE INDEX cci_fact_transactions ON dbo.fact_transactions ON ps_month (date_key);
CREATE NONCLUSTERED INDEX ix_alert_queue ON dbo.fact_transactions (is_alert, fraud_probability DESC)
    INCLUDE (txn_id, txn_time, customer_key, amount) WHERE is_alert = 1 ON ps_month (date_key);
GO

CREATE VIEW dbo.vw_daily_fraud AS
SELECT d.full_date,
       COUNT_BIG(*)                                                   AS transactions,
       SUM(f.amount)                                                  AS amount,
       SUM(CAST(f.is_fraud AS INT))                                   AS frauds,
       SUM(CAST(f.is_alert AS INT))                                   AS alerts,
       SUM(CASE WHEN f.is_alert = 1 AND f.is_fraud = 1 THEN 1 ELSE 0 END) AS true_alerts,
       SUM(CASE WHEN f.is_alert = 1 AND f.is_fraud = 1 THEN f.amount ELSE 0 END) AS fraud_amount_caught
FROM dbo.fact_transactions f JOIN dbo.dim_date d ON d.date_key = f.date_key
GROUP BY d.full_date;
GO

CREATE VIEW dbo.vw_alert_queue AS
SELECT f.txn_id, f.txn_time, c.customer_id, c.segment, m.category, f.channel, f.txn_city,
       f.amount, f.fraud_probability, f.anomaly_score, f.is_fraud
FROM dbo.fact_transactions f
JOIN dbo.dim_customer c ON c.customer_key = f.customer_key
JOIN dbo.dim_merchant m ON m.merchant_key = f.merchant_key
WHERE f.is_alert = 1;
GO
