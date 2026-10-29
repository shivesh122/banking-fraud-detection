"""
Simulates 6 months of retail-banking card/UPI transactions with realistic fraud patterns.

Legitimate behaviour
  * each customer has a home city, 1-2 devices, a spending level and a segment
  * daily activity, time-of-day, channel and merchant mix follow typical patterns
  * genuine "risky-looking" behaviour is included on purpose (travel, big-ticket purchases,
    new phones) so the model has to learn the difference

Fraud patterns (episodes on ~2% of customers)
  * account takeover   - new device, night-time, several high-value online/UPI purchases
  * card testing       - burst of tiny online payments, then a large one
  * cloned card        - card-present spends / ATM withdrawals in a far-away city
  * compromised merchant - small number of high-risk merchants with fraudulent charges

Usage: python scripts/generate_data.py [--as-of YYYY-MM-DD] [--days 180] [--customers 3000]
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

CITIES = {
    # name: (lat, lon, weight as home city)
    "Mumbai": (19.08, 72.88, 14), "Delhi": (28.61, 77.21, 14), "Bengaluru": (12.97, 77.59, 12),
    "Hyderabad": (17.39, 78.49, 8), "Chennai": (13.08, 80.27, 8), "Kolkata": (22.57, 88.36, 8),
    "Pune": (18.52, 73.86, 6), "Ahmedabad": (23.02, 72.57, 5), "Jaipur": (26.91, 75.79, 4),
    "Lucknow": (26.85, 80.95, 4), "Patna": (25.59, 85.14, 4), "Gorakhpur": (26.76, 83.37, 3),
    "Kochi": (9.93, 76.27, 3), "Indore": (22.72, 75.86, 3), "Chandigarh": (30.73, 76.78, 3),
    "Dubai": (25.20, 55.27, 0), "Singapore": (1.35, 103.82, 0), "London": (51.51, -0.13, 0),
}
INTERNATIONAL = {"Dubai", "Singapore", "London"}

# category: (channels with weights, amount multiplier, share of legit spend)
CATEGORIES = {
    "Grocery": ({"POS": 0.6, "UPI": 0.4}, 0.6, 0.20),
    "Restaurants": ({"POS": 0.5, "UPI": 0.5}, 0.5, 0.14),
    "Fuel": ({"POS": 0.7, "UPI": 0.3}, 0.8, 0.08),
    "E-commerce": ({"Online": 1.0}, 1.0, 0.16),
    "Utilities": ({"Online": 0.5, "UPI": 0.5}, 1.1, 0.07),
    "Pharmacy": ({"POS": 0.6, "UPI": 0.4}, 0.4, 0.05),
    "Travel": ({"Online": 1.0}, 3.5, 0.04),
    "Electronics": ({"POS": 0.4, "Online": 0.6}, 4.0, 0.04),
    "Jewellery": ({"POS": 1.0}, 6.0, 0.015),
    "Gift Cards": ({"Online": 1.0}, 1.5, 0.01),
    "Gaming & Crypto": ({"Online": 1.0}, 1.2, 0.015),
    "ATM": ({"ATM": 1.0}, 2.0, 0.08),
    "Transfers": ({"UPI": 1.0}, 1.5, 0.10),
}
HIGH_RISK = {"Electronics", "Jewellery", "Gift Cards", "Gaming & Crypto"}
SEGMENTS = {"Student": (0.25, 450), "Retail": (0.5, 1200), "Premium": (0.15, 4500), "SME": (0.10, 3000)}


def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def make_customers(rng, n, start):
    home_cities = [c for c, v in CITIES.items() if v[2] > 0]
    w = np.array([CITIES[c][2] for c in home_cities], float)
    segs = list(SEGMENTS)
    seg = rng.choice(segs, n, p=[SEGMENTS[s][0] for s in segs])
    typical = np.array([SEGMENTS[s][1] for s in seg]) * rng.lognormal(0, 0.35, n)
    tenure_days = rng.integers(30, 3650, n)
    return pd.DataFrame(
        {
            "customer_id": [f"C{i:05d}" for i in range(1, n + 1)],
            "segment": seg,
            "home_city": rng.choice(home_cities, n, p=w / w.sum()),
            "account_open_date": [(start - timedelta(days=int(t))).isoformat() for t in tenure_days],
            "typical_spend": typical.round(0),
            "daily_rate": np.clip(rng.gamma(2.2, 0.16, n), 0.05, 1.6).round(3),
            "n_devices": rng.choice([1, 2], n, p=[0.7, 0.3]),
        }
    )


def make_merchants(rng, n=650):
    cats = list(CATEGORIES)
    share = np.array([CATEGORIES[c][2] for c in cats])
    cat = rng.choice(cats, n, p=share / share.sum())
    cities = list(CITIES)
    cw = np.array([max(CITIES[c][2], 1) for c in cities], float)
    online = np.array([set(CATEGORIES[c][0]) == {"Online"} for c in cat])
    city = np.where(online, "Online", rng.choice(cities, n, p=cw / cw.sum()))
    return pd.DataFrame(
        {"merchant_id": [f"M{i:04d}" for i in range(1, n + 1)], "category": cat, "merchant_city": city}
    )


def pick_channel(rng, category):
    ch = CATEGORIES[category][0]
    return rng.choice(list(ch), p=list(ch.values()))


def hour_legit(rng, size):
    # daytime-heavy distribution
    p = np.array([1, .5, .3, .3, .4, .8, 2, 4, 6, 7, 8, 8, 9, 8, 7, 7, 7, 8, 9, 10, 9, 7, 4, 2], float)
    return rng.choice(24, size, p=p / p.sum())


def simulate(as_of: date, days: int, n_customers: int, seed: int = 11):
    rng = np.random.default_rng(seed)
    start = as_of - timedelta(days=days - 1)
    customers = make_customers(rng, n_customers, start)
    merchants = make_merchants(rng)
    by_cat = {c: g for c, g in merchants.groupby("category")}
    cats = list(CATEGORIES)
    share = np.array([CATEGORIES[c][2] for c in cats])
    share = share / share.sum()

    rows = []
    t0 = datetime.combine(start, datetime.min.time())

    pool_cache: dict = {}

    def merchant_for(cat, city):
        key = (cat, city)
        if key not in pool_cache:
            g = by_cat[cat]
            local = g[(g.merchant_city == city) | (g.merchant_city == "Online")]
            g = local if len(local) else g
            pool_cache[key] = list(g.itertuples(index=False))
        pool = pool_cache[key]
        return pool[rng.integers(len(pool))]

    for c in customers.itertuples(index=False):
        devices = [f"D{c.customer_id[1:]}-{k}" for k in range(c.n_devices)]
        favourite = {}
        n = rng.poisson(c.daily_rate * days)
        if n == 0:
            continue
        day = np.sort(rng.integers(0, days, n))
        hours = hour_legit(rng, n)
        mins = rng.integers(0, 60, n)
        cat_draw = rng.choice(cats, n, p=share)
        # travel episodes: a few days in another city (genuine, but looks like geo-anomaly)
        travel: dict = {}
        if rng.random() < 0.30:
            d0 = int(rng.integers(0, days - 8))
            travel_city = rng.choice([x for x in CITIES if x != c.home_city])
            travel = {d: travel_city for d in range(d0, d0 + int(rng.integers(2, 9)))}
        # genuine new phones and occasional family/shared devices (looks like account takeover)
        new_phone_day = int(rng.integers(0, days)) if rng.random() < 0.25 else None
        family_device = f"D{c.customer_id[1:]}-fam"
        for i in range(n):
            cat = cat_draw[i]
            city = travel.get(int(day[i]), c.home_city)
            if city in INTERNATIONAL and cat == "ATM":
                cat = "Restaurants"
            ch = pick_channel(rng, cat)
            # customers mostly reuse a handful of merchants per category
            key = (cat, city)
            if key in favourite and rng.random() < 0.7:
                m = favourite[key]
            else:
                m = merchant_for(cat, city)
                favourite.setdefault(key, m)
            mult = CATEGORIES[cat][1]
            amt = c.typical_spend * mult * rng.lognormal(0, 0.6)
            if rng.random() < 0.03:  # genuine big-ticket purchase
                amt *= rng.uniform(3, 10)
            dev = devices[0] if ch in ("Online", "UPI") else ""
            if ch in ("Online", "UPI") and len(devices) > 1 and rng.random() < 0.3:
                dev = devices[1]
            if ch in ("Online", "UPI") and rng.random() < 0.02:
                dev = family_device
            if new_phone_day is not None and day[i] >= new_phone_day and ch in ("Online", "UPI"):
                dev = f"D{c.customer_id[1:]}-new"
            ts = t0 + timedelta(days=int(day[i]), hours=int(hours[i]), minutes=int(mins[i]))
            txn_city = city if ch != "Online" else c.home_city
            rows.append((c.customer_id, ts, m.merchant_id, cat, ch, round(max(amt, 10), 2), txn_city, dev, 0, ""))
            # genuine bursts of small UPI payments (splitting bills, shopping) - looks like card testing
            if rng.random() < 0.04:
                for k in range(int(rng.integers(2, 6))):
                    mm = merchant_for(rng.choice(["Grocery", "Restaurants", "Transfers"]), city)
                    rows.append((c.customer_id, ts + timedelta(minutes=int((k + 1) * rng.integers(2, 12))), mm.merchant_id, mm.category, "UPI",
                                 round(float(rng.uniform(20, 400)), 2), city, dev or devices[0], 0, ""))

    legit_count = len(rows)

    # ---------------- fraud episodes ----------------
    victims = customers.sample(frac=0.05, random_state=seed)
    compromised = merchants[merchants.category.isin(["Gift Cards", "Gaming & Crypto", "E-commerce"])].sample(5, random_state=seed)
    domestic = [x for x in CITIES if x not in INTERNATIONAL]
    for c in victims.itertuples(index=False):
        kind = rng.choice(["account_takeover", "card_testing", "cloned_card", "compromised_merchant"], p=[0.35, 0.25, 0.25, 0.15])
        base = t0 + timedelta(days=int(rng.integers(20, days - 1)), hours=int(rng.integers(0, 24)), minutes=int(rng.integers(0, 60)))
        own_device = f"D{c.customer_id[1:]}-0"
        fdev = f"FD{rng.integers(10**6)}"
        if kind == "account_takeover":
            # 60% from the fraudster's device, 40% via the customer's own phone (malware / remote access)
            dev = fdev if rng.random() < 0.6 else own_device
            if rng.random() < 0.5:
                base = base.replace(hour=int(rng.choice([0, 1, 2, 3, 4, 23, 22])))
            for k in range(int(rng.integers(1, 5))):
                cat = rng.choice(["Electronics", "Gift Cards", "E-commerce", "Transfers", "Transfers"])
                ch = "UPI" if cat == "Transfers" else "Online"
                m = by_cat[cat].iloc[rng.integers(len(by_cat[cat]))]
                amt = c.typical_spend * rng.uniform(2.5, 12)
                rows.append((c.customer_id, base + timedelta(minutes=int(k * rng.integers(5, 90))), m.merchant_id, cat, ch, round(amt, 2), c.home_city, dev, 1, kind))
        elif kind == "card_testing":
            g = by_cat["E-commerce"]
            for k in range(int(rng.integers(3, 9))):
                m = g.iloc[rng.integers(len(g))]
                rows.append((c.customer_id, base + timedelta(minutes=int(k * rng.integers(1, 10))), m.merchant_id, "E-commerce", "Online",
                             round(float(rng.uniform(1, 150)), 2), c.home_city, fdev if rng.random() < 0.7 else own_device, 1, kind))
            for k in range(int(rng.integers(0, 3))):
                cat = rng.choice(["Electronics", "Gift Cards", "E-commerce"])
                m = by_cat[cat].iloc[rng.integers(len(by_cat[cat]))]
                rows.append((c.customer_id, base + timedelta(minutes=60 + 15 * k), m.merchant_id, cat, "Online", round(c.typical_spend * rng.uniform(2, 10), 2), c.home_city, fdev, 1, kind))
        elif kind == "cloned_card":
            city = rng.choice([x for x in domestic if x != c.home_city])
            for k in range(int(rng.integers(1, 5))):
                cat = rng.choice(["ATM", "Electronics", "Jewellery", "ATM", "Fuel", "Grocery"])
                m = merchant_for(cat, city)
                amt = rng.choice([5000, 10000, 20000]) if cat == "ATM" else c.typical_spend * CATEGORIES[cat][1] * rng.uniform(1.5, 6)
                ch = "ATM" if cat == "ATM" else "POS"
                rows.append((c.customer_id, base + timedelta(minutes=int(k * rng.integers(10, 120))), m.merchant_id, cat, ch, round(float(amt), 2), city, "", 1, kind))
        else:
            m = compromised.iloc[rng.integers(len(compromised))]
            for k in range(int(rng.integers(1, 4))):
                rows.append((c.customer_id, base + timedelta(hours=int(k * rng.integers(2, 30))), m.merchant_id, m.category, "Online",
                             round(c.typical_spend * rng.uniform(1, 4), 2), c.home_city, fdev if rng.random() < 0.3 else own_device, 1, kind))

    tx = pd.DataFrame(rows, columns=["customer_id", "timestamp", "merchant_id", "category", "channel", "amount", "txn_city", "device_id", "is_fraud", "fraud_type"])
    tx = tx[tx["timestamp"] < datetime.combine(as_of + timedelta(days=1), datetime.min.time())]
    tx = tx.sort_values("timestamp", kind="stable").reset_index(drop=True)
    tx.insert(0, "txn_id", [f"T{i:07d}" for i in range(1, len(tx) + 1)])
    tx["timestamp"] = tx["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    print(f"  legit={legit_count:,} fraud={int(tx.is_fraud.sum()):,} ({tx.is_fraud.mean():.2%})")
    cities = pd.DataFrame([(k, v[0], v[1], k in INTERNATIONAL) for k, v in CITIES.items()], columns=["city", "lat", "lon", "is_international"])
    return customers.drop(columns=["daily_rate", "n_devices"]), merchants, cities, tx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=date.today().isoformat())
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--customers", type=int, default=3000)
    a = ap.parse_args()
    customers, merchants, cities, tx = simulate(date.fromisoformat(a.as_of), a.days, a.customers)
    RAW.mkdir(parents=True, exist_ok=True)
    customers.to_csv(RAW / "customers.csv", index=False)
    merchants.to_csv(RAW / "merchants.csv", index=False)
    cities.to_csv(RAW / "cities.csv", index=False)
    tx.to_csv(RAW / "transactions.csv", index=False)
    print(f"Generated {len(tx):,} transactions for {len(customers):,} customers as of {a.as_of}")


if __name__ == "__main__":
    main()
