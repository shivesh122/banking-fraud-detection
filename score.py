"""
Score transactions from the command line with the trained model.

  python score.py data/raw/transactions.csv --top 20
"""
import argparse

import joblib
import pandas as pd

from fraud import features as fe
from fraud.config import MODEL_DIR, RAW
from fraud.model import score_all
from fraud.reasons import reasons_for


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transactions", nargs="?", default=str(RAW / "transactions.csv"))
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    bundle = joblib.load(MODEL_DIR / "fraud_model.joblib")
    _, customers, merchants, cities = fe.load_raw()
    tx = pd.read_csv(a.transactions, parse_dates=["timestamp"], keep_default_na=False, na_values=[""])
    tx, _ = fe.clean(tx)
    df = score_all(fe.build_features(tx, customers, merchants, cities), bundle["iforest"], bundle["gbm"])
    top = df.sort_values("fraud_probability", ascending=False).head(a.top)
    for r in top.to_dict("records"):
        flag = "ALERT" if r["fraud_probability"] >= bundle["threshold"] else "ok   "
        why = "; ".join(x["text"] for x in reasons_for(r)) or "anomalous pattern"
        print(f"{flag} {r['txn_id']} {r['timestamp']:%Y-%m-%d %H:%M} ₹{r['amount']:>10,.2f}  p={r['fraud_probability']:.3f}  {why}")


if __name__ == "__main__":
    main()
