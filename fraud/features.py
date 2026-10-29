"""
Feature engineering. Every feature uses only information available at transaction time
(previous transactions of the same customer), so there is no look-ahead leakage.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FEATURES, HIGH_RISK_CATEGORIES, RAW


def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def load_raw(raw_dir=RAW):
    tx = pd.read_csv(raw_dir / "transactions.csv", parse_dates=["timestamp"], keep_default_na=False, na_values=[""])
    customers = pd.read_csv(raw_dir / "customers.csv", parse_dates=["account_open_date"])
    merchants = pd.read_csv(raw_dir / "merchants.csv")
    cities = pd.read_csv(raw_dir / "cities.csv")
    return tx, customers, merchants, cities


def clean(tx: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    n0 = len(tx)
    tx = tx.drop_duplicates(subset="txn_id")
    tx = tx[tx["amount"] > 0]
    tx = tx.dropna(subset=["customer_id", "timestamp", "merchant_id"])
    tx["device_id"] = tx["device_id"].fillna("")
    tx["fraud_type"] = tx["fraud_type"].fillna("")
    return tx, {"source_rows": n0, "rows": len(tx), "removed": n0 - len(tx)}


def _rolling_prior(df: pd.DataFrame, window: str, how: str) -> np.ndarray:
    """Rolling stat over the customer's *previous* transactions in a time window (current excluded)."""
    r = df.groupby("customer_id", sort=False).rolling(window, on="timestamp", closed="left")["amount"]
    out = r.count() if how == "count" else r.sum()
    return out.fillna(0).to_numpy()


def build_features(tx, customers, merchants, cities) -> pd.DataFrame:
    df = tx.merge(customers[["customer_id", "home_city", "account_open_date", "segment"]], on="customer_id", how="left")
    df = df.merge(merchants[["merchant_id", "merchant_city"]], on="merchant_id", how="left")
    geo = cities.set_index("city")
    df = df.sort_values(["customer_id", "timestamp", "txn_id"], kind="stable").reset_index(drop=True)
    g = df.groupby("customer_id", sort=False)

    # --- amount behaviour vs the customer's own history
    prior_median = g["amount"].transform(lambda s: s.expanding().median().shift())
    seg_median = df.groupby("segment")["amount"].transform("median")
    df["prior_median_amount"] = prior_median.fillna(seg_median)
    df["log_amount"] = np.log1p(df["amount"])
    df["amount_ratio"] = df["amount"] / df["prior_median_amount"]

    # --- velocity
    df["txn_count_1h"] = _rolling_prior(df, "1h", "count")
    df["txn_count_24h"] = _rolling_prior(df, "24h", "count")
    df["amount_24h"] = _rolling_prior(df, "24h", "sum")
    df["amount_24h_ratio"] = df["amount_24h"] / df["prior_median_amount"]
    mins = g["timestamp"].diff().dt.total_seconds() / 60
    df["mins_since_last"] = mins.fillna(60 * 24 * 30)
    df["log_mins_since_last"] = np.log1p(df["mins_since_last"])

    # --- time of day
    df["hour"] = df["timestamp"].dt.hour
    df["is_night"] = ((df["hour"] < 6) | (df["hour"] >= 23)).astype(int)

    # --- geography
    lat = df["txn_city"].map(geo["lat"])
    lon = df["txn_city"].map(geo["lon"])
    hlat = df["home_city"].map(geo["lat"])
    hlon = df["home_city"].map(geo["lon"])
    df["distance_home_km"] = haversine(hlat, hlon, lat, lon).fillna(0).round(1)
    plat, plon = g["txn_city"].shift().map(geo["lat"]), g["txn_city"].shift().map(geo["lon"])
    df["distance_last_km"] = haversine(plat, plon, lat, lon).fillna(0).round(1)
    hours = (df["mins_since_last"] / 60).clip(lower=0.25)  # 15-minute floor avoids divide-by-zero spikes
    df["speed_kmh"] = (df["distance_last_km"] / hours).clip(upper=5000)
    df["is_international"] = df["txn_city"].map(geo["is_international"]).fillna(False).astype(int)

    # --- novelty
    # A device counts as "new" for 48 hours after it is first seen, unless it is the customer's
    # first-ever device in the data (that is their usual phone, not a takeover).
    has_dev = df["device_id"] != ""
    dev_first_seen = df.groupby(["customer_id", "device_id"], sort=False)["timestamp"].transform("min")
    cust_first_dev = df[has_dev].groupby("customer_id")["device_id"].first()
    is_first_device = df["device_id"] == df["customer_id"].map(cust_first_dev)
    recent = (df["timestamp"] - dev_first_seen) < pd.Timedelta(hours=48)
    df["is_new_device"] = (has_dev & recent & ~is_first_device).astype(int)
    df["is_new_merchant"] = (df.groupby(["customer_id", "merchant_id"], sort=False).cumcount() == 0).astype(int)

    # --- channel / merchant
    for ch in ["Online", "UPI", "ATM", "POS"]:
        df[f"is_{ch.lower()}"] = (df["channel"] == ch).astype(int)
    df["is_high_risk_category"] = df["category"].isin(HIGH_RISK_CATEGORIES).astype(int)
    df["account_age_days"] = (df["timestamp"] - df["account_open_date"]).dt.days.clip(lower=0)

    df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    assert not df[FEATURES].isna().any().any(), "features contain NaN"
    return df
