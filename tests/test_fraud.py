import json
import shutil
import subprocess
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from fraud.features import build_features, clean, haversine
from fraud.model import _avg_path_length, metrics_at
from fraud.reasons import reasons_for

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    customers = pd.DataFrame({
        "customer_id": ["C1", "C2"], "segment": ["Retail", "Retail"], "home_city": ["Delhi", "Mumbai"],
        "account_open_date": pd.to_datetime(["2024-01-01", "2025-06-01"]), "typical_spend": [1000, 800],
    })
    merchants = pd.DataFrame({"merchant_id": ["M1", "M2", "M3"], "category": ["Grocery", "Electronics", "ATM"],
                              "merchant_city": ["Delhi", "Online", "Kolkata"]})
    cities = pd.DataFrame({"city": ["Delhi", "Mumbai", "Kolkata"], "lat": [28.61, 19.08, 22.57], "lon": [77.21, 72.88, 88.36],
                           "is_international": [False, False, False]})
    tx = pd.DataFrame({
        "txn_id": ["T1", "T2", "T3", "T4", "T5", "T6"],
        "customer_id": ["C1", "C1", "C1", "C1", "C1", "C2"],
        "timestamp": pd.to_datetime(["2026-01-01 10:00", "2026-01-02 10:00", "2026-01-03 02:00", "2026-01-03 02:10",
                                     "2026-01-03 02:20", "2026-01-03 12:00"]),
        "merchant_id": ["M1", "M1", "M2", "M2", "M3", "M1"],
        "category": ["Grocery", "Grocery", "Electronics", "Electronics", "ATM", "Grocery"],
        "channel": ["UPI", "UPI", "Online", "Online", "ATM", "POS"],
        "amount": [1000.0, 1200.0, 15000.0, 14000.0, 20000.0, 500.0],
        "txn_city": ["Delhi", "Delhi", "Delhi", "Delhi", "Kolkata", "Mumbai"],
        "device_id": ["D1", "D1", "FD9", "FD9", "", ""],
        "is_fraud": [0, 0, 1, 1, 1, 0],
        "fraud_type": ["", "", "account_takeover", "account_takeover", "cloned_card", ""],
    })
    return tx, customers, merchants, cities


class FeatureTests(unittest.TestCase):
    def setUp(self):
        tx, c, m, ci = fixture()
        tx, self.stats = clean(tx)
        self.df = build_features(tx, c, m, ci).set_index("txn_id")

    def test_velocity_counts_only_previous_transactions(self):
        self.assertEqual(self.df.loc["T1", "txn_count_1h"], 0)
        self.assertEqual(self.df.loc["T4", "txn_count_1h"], 1)
        self.assertEqual(self.df.loc["T5", "txn_count_1h"], 2)

    def test_amount_ratio_uses_prior_history(self):
        # median of the previous two transactions (1000, 1200) = 1100
        self.assertAlmostEqual(self.df.loc["T3", "amount_ratio"], 15000 / 1100, places=4)

    def test_new_device_and_merchant(self):
        self.assertEqual(self.df.loc["T1", "is_new_device"], 0)  # customer's usual phone
        self.assertEqual(self.df.loc["T3", "is_new_device"], 1)
        self.assertEqual(self.df.loc["T2", "is_new_merchant"], 0)
        self.assertEqual(self.df.loc["T3", "is_new_merchant"], 1)

    def test_geography(self):
        self.assertGreater(self.df.loc["T5", "distance_home_km"], 1000)
        self.assertGreater(self.df.loc["T5", "speed_kmh"], 500)  # Delhi -> Kolkata in 10 minutes
        self.assertEqual(self.df.loc["T3", "is_night"], 1)
        self.assertAlmostEqual(float(haversine(28.61, 77.21, 19.08, 72.88)), 1150, delta=20)


class ModelTests(unittest.TestCase):
    def test_average_path_length(self):
        self.assertEqual(_avg_path_length(1), 0.0)
        self.assertEqual(_avg_path_length(2), 1.0)
        self.assertAlmostEqual(_avg_path_length(256), 10.2448, places=3)

    def test_metrics_at_threshold(self):
        y = np.array([1, 1, 0, 0, 0])
        p = np.array([0.9, 0.2, 0.8, 0.1, 0.05])
        amt = np.array([1000.0, 500.0, 50.0, 10.0, 10.0])
        m = metrics_at(y, p, amt, 0.5)
        self.assertEqual((m["tp"], m["fp"], m["fn"], m["tn"]), (1, 1, 1, 2))
        self.assertEqual(m["precision"], 0.5)
        self.assertEqual(m["fraud_amount_caught"], 1000)

    def test_reason_codes(self):
        row = {"is_new_device": 1, "amount_ratio": 9.2, "txn_count_1h": 0, "amount_24h_ratio": 1, "speed_kmh": 0,
               "distance_home_km": 0, "is_night": 1, "is_high_risk_category": 0, "log_mins_since_last": 5, "is_new_merchant": 0}
        codes = [r["code"] for r in reasons_for(row)]
        self.assertEqual(codes, ["NEW_DEVICE", "AMOUNT_SPIKE", "NIGHT"])


@unittest.skipUnless(shutil.which("node") and (ROOT / "data/processed/parity_sample.json").exists(), "needs node and a built model")
class BrowserScorerParity(unittest.TestCase):
    def test_javascript_matches_sklearn(self):
        out = subprocess.run(["node", str(ROOT / "tests" / "parity.js")], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(json.loads(out.stdout)["decision_flips"], 0)


if __name__ == "__main__":
    unittest.main()
