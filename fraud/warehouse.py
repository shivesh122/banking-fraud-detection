"""Loads scored transactions into the SQLite star schema and exports CSVs for Power BI."""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from .config import DB_PATH, EXPORTS, HIGH_RISK_CATEGORIES, SQL_DIR


def build_star(scored: pd.DataFrame, customers: pd.DataFrame, merchants: pd.DataFrame) -> dict[str, pd.DataFrame]:
    dates = pd.date_range(scored["timestamp"].min().normalize(), scored["timestamp"].max().normalize(), freq="D")
    dim_date = pd.DataFrame(
        {
            "date_key": dates.strftime("%Y%m%d").astype(int),
            "full_date": dates.strftime("%Y-%m-%d"),
            "year": dates.year,
            "month": dates.month,
            "year_month": dates.strftime("%Y-%m"),
            "week_start": (dates - pd.to_timedelta(dates.dayofweek, unit="D")).strftime("%Y-%m-%d"),
            "day_of_week": dates.strftime("%a"),
            "is_weekend": (dates.dayofweek >= 5).astype(int),
        }
    )
    dim_customer = customers[["customer_id", "segment", "home_city", "account_open_date"]].copy()
    dim_customer["account_open_date"] = pd.to_datetime(dim_customer["account_open_date"]).dt.strftime("%Y-%m-%d")
    dim_customer.insert(0, "customer_key", np.arange(1, len(dim_customer) + 1))
    dim_merchant = merchants[["merchant_id", "category", "merchant_city"]].copy()
    dim_merchant["is_high_risk"] = dim_merchant["category"].isin(HIGH_RISK_CATEGORIES).astype(int)
    dim_merchant.insert(0, "merchant_key", np.arange(1, len(dim_merchant) + 1))

    f = scored
    fact = pd.DataFrame(
        {
            "txn_id": f["txn_id"],
            "date_key": f["timestamp"].dt.strftime("%Y%m%d").astype(int),
            "txn_time": f["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S"),
            "hour": f["hour"],
            "customer_key": f["customer_id"].map(dim_customer.set_index("customer_id")["customer_key"]),
            "merchant_key": f["merchant_id"].map(dim_merchant.set_index("merchant_id")["merchant_key"]),
            "channel": f["channel"],
            "txn_city": f["txn_city"],
            "amount": f["amount"].round(2),
            "amount_ratio": f["amount_ratio"].round(3),
            "txn_count_1h": f["txn_count_1h"].astype(int),
            "distance_home_km": f["distance_home_km"],
            "is_new_device": f["is_new_device"],
            "anomaly_score": f["anomaly_score"].round(5),
            "fraud_probability": f["fraud_probability"].round(5),
            "is_alert": f["is_alert"].astype(int),
            "is_fraud": f["is_fraud"].astype(int),
            "fraud_type": f["fraud_type"].replace("", None),
            "dataset": f["dataset"],
        }
    )
    if fact[["customer_key", "merchant_key"]].isna().any().any():
        raise ValueError("Transactions reference unknown customers or merchants")
    return {"dim_date": dim_date, "dim_customer": dim_customer, "dim_merchant": dim_merchant, "fact_transactions": fact}


def load_sqlite(tables: dict[str, pd.DataFrame], db_path=DB_PATH) -> dict[str, int]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript((SQL_DIR / "schema_sqlite.sql").read_text())
        with con:
            for name in ["dim_date", "dim_customer", "dim_merchant", "fact_transactions"]:
                df = tables[name]
                rows = df.astype(object).where(pd.notna(df), None).itertuples(index=False, name=None)
                con.executemany(f"INSERT INTO {name} ({', '.join(df.columns)}) VALUES ({', '.join('?' * len(df.columns))})", rows)
        con.execute("ANALYZE")
        return {n: len(t) for n, t in tables.items()}
    finally:
        con.close()


def run_quality_checks(db_path=DB_PATH) -> list[dict]:
    checks = [
        ("unique transaction ids", "SELECT COUNT(*) = COUNT(DISTINCT txn_id) FROM fact_transactions"),
        ("every transaction has a customer", "SELECT COUNT(*) = 0 FROM fact_transactions f LEFT JOIN dim_customer c USING (customer_key) WHERE c.customer_id IS NULL"),
        ("every transaction has a merchant", "SELECT COUNT(*) = 0 FROM fact_transactions f LEFT JOIN dim_merchant m USING (merchant_key) WHERE m.merchant_id IS NULL"),
        ("amounts are positive", "SELECT COUNT(*) = 0 FROM fact_transactions WHERE amount <= 0"),
        ("probabilities within 0-1", "SELECT COUNT(*) = 0 FROM fact_transactions WHERE fraud_probability < 0 OR fraud_probability > 1"),
        ("labelled frauds have a type", "SELECT COUNT(*) = 0 FROM fact_transactions WHERE is_fraud = 1 AND fraud_type IS NULL"),
        ("test period after training period", "SELECT (SELECT MIN(txn_time) FROM fact_transactions WHERE dataset='test') > (SELECT MAX(txn_time) FROM fact_transactions WHERE dataset='train')"),
    ]
    con = sqlite3.connect(db_path)
    try:
        res = [{"check": n, "passed": bool(con.execute(q).fetchone()[0])} for n, q in checks]
    finally:
        con.close()
    failed = [r["check"] for r in res if not r["passed"]]
    if failed:
        raise AssertionError(f"Data quality checks failed: {failed}")
    return res


def export_csv(tables: dict[str, pd.DataFrame], out=EXPORTS) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(out / f"{name}.csv", index=False)
