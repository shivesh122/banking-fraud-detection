# Power BI report for the fraud model

The pipeline publishes a star schema (`/exports/*.csv`, or SQL Server via `sql/schema_sqlserver.sql`)
with every transaction's anomaly score, fraud probability, alert flag and confirmed label.

## 1. Load (Power Query)

1. Create parameters `ExportsFolder` (Text), `RangeStart` and `RangeEnd` (Date/Time).
2. Add the queries from [`power_query.m`](power_query.m): `fnLoadCsv`, `fact_transactions`, `dim_customer`, `dim_merchant`, `dim_date`.
3. *Close & Apply*.

## 2. Star schema relationships

| From (many) | To (one) |
|---|---|
| `fact_transactions[date_key]` | `dim_date[date_key]` |
| `fact_transactions[customer_key]` | `dim_customer[customer_key]` |
| `fact_transactions[merchant_key]` | `dim_merchant[merchant_key]` |

Single-direction filters, `dim_date` marked as the date table, key columns hidden. Only the fact table is large,
and every dimension is small, which keeps the VertiPaq model compact and queries fast.

## 3. Incremental refresh (performance)

1. Right-click `fact_transactions` → *Incremental refresh*.
2. Archive data starting **12 months** before refresh date; incrementally refresh **7 days**.
3. Tick *Detect data changes* on `txn_time` (optional) and *Only refresh complete days*.
4. Publish to the Power BI Service and schedule a daily refresh: only the last 7 days are re-imported,
   older partitions are kept, so refreshes stay fast as volume grows.

With SQL Server as the source, the `RangeStart`/`RangeEnd` filter folds to the database and uses the monthly
partitions and clustered columnstore index defined in `schema_sqlserver.sql`.

## 4. Measures

Add [`dax_measures.dax`](dax_measures.dax): precision, recall, F1, false-positive rate, fraud ₹ caught/missed,
net savings (with what-if parameters for review cost and recovery rate), time-intelligence comparisons.

## 5. Report pages

| Page | Visuals |
|---|---|
| **Executive** | Cards: Fraud Amount Caught, Recall %, Precision %, Net Savings, Alerts per Day · Line: Alerts vs Fraud Transactions by day · Bar: Fraud Amount by `dim_merchant[category]` |
| **Alert queue** | Table filtered to `is_alert = 1`, sorted by `fraud_probability`, conditional formatting on probability · Slicers: channel, category, risk_band, date |
| **Model quality** | Matrix: `is_alert` × `is_fraud` (confusion matrix) · What-if slicers for review cost and recovery rate driving Net Savings · Precision/Recall by `fraud_type` |
| **Patterns** | Column: Fraud Rate % by `hour` · Map: fraud by `txn_city` · Decomposition tree on Fraud Amount (channel → category → city) |
