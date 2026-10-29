from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
DB_PATH = ROOT / "data" / "warehouse" / "fraud.db"
SITE_DATA = ROOT / "site" / "data"
MODEL_DIR = ROOT / "models"
EXPORTS = ROOT / "exports"
SQL_DIR = ROOT / "sql"

WARMUP_DAYS = 14          # history needed before features are reliable; not used for training
TEST_DAYS = 60            # most recent days are held out (time-based split, no look-ahead)

HIGH_RISK_CATEGORIES = {"Electronics", "Jewellery", "Gift Cards", "Gaming & Crypto"}

# Business assumptions for choosing the alert threshold
REVIEW_COST = 150         # ₹ cost for an analyst to review one alert
RECOVERY_RATE = 0.85      # share of a fraud's amount saved when it is caught in time

# Order matters: the exported model and the in-browser scorer use this order
FEATURES = [
    "log_amount",
    "amount_ratio",
    "amount_24h_ratio",
    "txn_count_1h",
    "txn_count_24h",
    "log_mins_since_last",
    "hour",
    "is_night",
    "distance_home_km",
    "speed_kmh",
    "is_new_device",
    "is_new_merchant",
    "is_online",
    "is_upi",
    "is_atm",
    "is_pos",
    "is_high_risk_category",
    "is_international",
    "account_age_days",
]
