"""
End-to-end build:
  raw data -> clean -> features -> train & evaluate -> score -> SQL star schema
  -> Power BI exports -> dashboard data + browser model

Usage:
  python build.py            # use existing data/raw
  python build.py --refresh  # regenerate simulated data (as of today) first
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

from fraud import features as fe
from fraud import model as md
from fraud import warehouse as wh
from fraud.config import FEATURES, MODEL_DIR, PROCESSED, RECOVERY_RATE, REVIEW_COST, ROOT, SITE_DATA, TEST_DAYS
from fraud.reasons import reasons_for

log = logging.getLogger("build")


def to_records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.replace({np.nan: None}).to_json(orient="records", date_format="iso"))


def build():
    t0 = time.perf_counter()
    log.info("Loading and cleaning raw data")
    tx, customers, merchants, cities = fe.load_raw()
    tx, clean_stats = fe.clean(tx)

    log.info("Engineering features for %s transactions", f"{len(tx):,}")
    df = fe.build_features(tx, customers, merchants, cities)

    log.info("Training Isolation Forest + Gradient Boosting (time-based split)")
    res = md.train_and_evaluate(df)
    iforest, gbm, thr = res["models"]["iforest"], res["models"]["gbm"], res["threshold"]

    scored = md.score_all(df, iforest, gbm)
    scored["is_alert"] = scored["fraud_probability"] >= thr
    split = res["split"]
    scored["dataset"] = np.where(
        scored["timestamp"] >= pd.Timestamp(split["test_start"]), "test",
        np.where(scored["timestamp"] >= pd.Timestamp(split["train_start"]), "train", "warmup"),
    )

    log.info("Loading SQL star schema and running data-quality checks")
    tables = wh.build_star(scored, customers, merchants)
    counts = wh.load_sqlite(tables)
    checks = wh.run_quality_checks()
    wh.export_csv(tables)

    log.info("Exporting models")
    MODEL_DIR.mkdir(exist_ok=True)
    joblib.dump({"iforest": iforest, "gbm": gbm, "threshold": thr, "features": FEATURES}, MODEL_DIR / "fraud_model.joblib")
    md.export_models(iforest, gbm, thr, ROOT / "site" / "model" / "model.json")

    # Parity sample: lets tests confirm the JavaScript scorer matches scikit-learn exactly
    test = scored[scored["dataset"] == "test"]
    sample = pd.concat([test[test["is_fraud"] == 1].head(100), test[test["is_fraud"] == 0].sample(300, random_state=1)])
    PROCESSED.mkdir(parents=True, exist_ok=True)
    (PROCESSED / "parity_sample.json").write_text(
        json.dumps({"X": sample[FEATURES].to_numpy(float).tolist(), "anomaly": sample["anomaly_score"].tolist(), "prob": sample["fraud_probability"].tolist()})
    )

    log.info("Building dashboard data")
    data = dashboard_data(scored, res, clean_stats, counts, checks)
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / "dashboard.json").write_text(json.dumps(data, separators=(",", ":")))
    log.info("Done in %.1fs", time.perf_counter() - t0)
    return data


def dashboard_data(scored, res, clean_stats, counts, checks) -> dict:
    test = scored[scored["dataset"] == "test"].copy()
    final = res["comparison"][-1]
    days = test["timestamp"].dt.normalize().nunique()
    fraud = test["is_fraud"] == 1
    alert = test["is_alert"]
    kpis = {
        "transactions": int(len(test)),
        "amount": round(float(test["amount"].sum()), 0),
        "frauds": int(fraud.sum()),
        "fraud_amount": round(float(test.loc[fraud, "amount"].sum()), 0),
        "fraud_rate_pct": round(100 * float(fraud.mean()), 3),
        "alerts": int(alert.sum()),
        "alerts_per_day": round(float(alert.sum()) / days, 1),
        "true_alerts": int((alert & fraud).sum()),
        "precision": final["precision"],
        "recall": final["recall"],
        "fpr": final["fpr"],
        "roc_auc": final["roc_auc"],
        "pr_auc": final["pr_auc"],
        "fraud_amount_caught": final["fraud_amount_caught"],
        "amount_recall": round(final["fraud_amount_caught"] / max(final["fraud_amount_caught"] + final["fraud_amount_missed"], 1), 4),
        "net_savings": final["net_savings"],
        "days": int(days),
    }

    test["date"] = test["timestamp"].dt.strftime("%Y-%m-%d")
    daily = (
        test.assign(caught=lambda d: d["is_alert"] & (d["is_fraud"] == 1), fraud_amt=lambda d: d["amount"] * d["is_fraud"],
                    caught_amt=lambda d: d["amount"] * (d["is_alert"] & (d["is_fraud"] == 1)))
        .groupby("date").agg(transactions=("txn_id", "count"), alerts=("is_alert", "sum"), true_alerts=("caught", "sum"),
                             frauds=("is_fraud", "sum"), fraud_amount=("fraud_amt", "sum"), caught_amount=("caught_amt", "sum"))
        .reset_index()
    )

    def breakdown(col):
        g = test.groupby(col).agg(transactions=("txn_id", "count"), frauds=("is_fraud", "sum"),
                                  caught=("is_alert", lambda s: int((s & (test.loc[s.index, "is_fraud"] == 1)).sum())),
                                  alerts=("is_alert", "sum"),
                                  fraud_amount=("amount", lambda s: float(s[test.loc[s.index, "is_fraud"] == 1].sum()))).reset_index()
        g["fraud_rate_pct"] = (100 * g["frauds"] / g["transactions"]).round(3)
        g["recall"] = (g["caught"] / g["frauds"].replace(0, np.nan)).round(3)
        return g.rename(columns={col: "name"}).sort_values("fraud_amount", ascending=False)

    hourly = scored.groupby("hour").agg(transactions=("txn_id", "count"), frauds=("is_fraud", "sum")).reset_index()
    hourly["fraud_rate_pct"] = (100 * hourly["frauds"] / hourly["transactions"]).round(3)

    # Analyst queue: most recent 14 days of alerts, highest probability first
    recent_cut = test["timestamp"].max() - pd.Timedelta(days=14)
    q = test[test["is_alert"] & (test["timestamp"] >= recent_cut)].sort_values("fraud_probability", ascending=False).head(250)
    alerts = []
    for r in q.to_dict("records"):
        alerts.append({
            "txn_id": r["txn_id"], "time": r["timestamp"].strftime("%Y-%m-%d %H:%M"), "customer_id": r["customer_id"],
            "segment": r["segment"], "home_city": r["home_city"], "category": r["category"], "channel": r["channel"],
            "txn_city": r["txn_city"], "amount": round(r["amount"], 2), "usual_amount": round(r["prior_median_amount"], 0),
            "probability": round(r["fraud_probability"], 4), "anomaly": round(r["anomaly_score"], 4),
            "confirmed_fraud": bool(r["is_fraud"]), "fraud_type": r["fraud_type"] or None,
            "reasons": [x["text"] for x in reasons_for(r)],
            # raw inputs so the alert can be re-scored live on the "Score a transaction" page
            "inputs": {
                "hour": int(r["hour"]), "txn_count_1h": int(r["txn_count_1h"]), "txn_count_24h": int(r["txn_count_24h"]),
                "spent_24h": r["amount_24h"], "mins_since_last": r["mins_since_last"],
                "distance_home_km": r["distance_home_km"], "distance_last_km": r["distance_last_km"],
                "new_device": bool(r["is_new_device"]), "new_merchant": bool(r["is_new_merchant"]),
                "international": bool(r["is_international"]), "account_age_days": int(r["account_age_days"]),
                "usual_amount": r["prior_median_amount"],
            },
        })

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "data_as_of": scored["timestamp"].max().strftime("%Y-%m-%d"),
            "split": res["split"],
            "test_days": TEST_DAYS,
            "train_seconds": res["train_seconds"],
            "assumptions": {"review_cost": REVIEW_COST, "recovery_rate": RECOVERY_RATE},
            "customers": int(scored["customer_id"].nunique()),
            "merchants": int(scored["merchant_id"].nunique()),
        },
        "kpis": kpis,
        "daily": to_records(daily),
        "by_channel": to_records(breakdown("channel")),
        "by_category": to_records(breakdown("category")),
        "hourly": to_records(hourly),
        "alerts": alerts,
        "model": {
            "threshold": res["threshold"],
            "comparison": res["comparison"],
            "roc": res["roc"],
            "pr": res["pr"],
            "threshold_table": res["threshold_table"],
            "importance": res["importance"],
            "recall_by_type": res["recall_by_type"],
        },
        "pipeline": {"clean": clean_stats, "rows_loaded": counts, "quality_checks": checks},
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="regenerate simulated data as of today")
    if ap.parse_args().refresh:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_data.py")], check=True)
    build()


if __name__ == "__main__":
    main()
