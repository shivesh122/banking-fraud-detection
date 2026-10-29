"""
Human-readable reason codes for an alert. The same rules are implemented in site/app.js
so explanations match between the batch pipeline and the live scorer.
"""
from __future__ import annotations

REASON_RULES = [
    # (code, test, message template)
    ("NEW_DEVICE", lambda r: r["is_new_device"] == 1, "Payment from a device first seen in the last 48 hours"),
    ("AMOUNT_SPIKE", lambda r: r["amount_ratio"] >= 5, "Amount is {amount_ratio:.1f}× the customer's usual spend"),
    ("VELOCITY_1H", lambda r: r["txn_count_1h"] >= 3, "{txn_count_1h:.0f} other transactions in the past hour"),
    ("BURST_24H", lambda r: r["amount_24h_ratio"] >= 6, "Spent {amount_24h_ratio:.1f}× usual amount in the past 24 hours"),
    ("IMPOSSIBLE_TRAVEL", lambda r: r["speed_kmh"] >= 500, "Implied travel speed of {speed_kmh:,.0f} km/h since last transaction"),
    ("FAR_FROM_HOME", lambda r: r["distance_home_km"] >= 500, "{distance_home_km:,.0f} km from the customer's home city"),
    ("NIGHT", lambda r: r["is_night"] == 1, "Made between 11 pm and 6 am"),
    ("HIGH_RISK_MCC", lambda r: r["is_high_risk_category"] == 1, "High-risk merchant category"),
    ("RAPID_REPEAT", lambda r: r["log_mins_since_last"] <= 1.8, "Less than 5 minutes after the previous transaction"),
    ("NEW_MERCHANT", lambda r: r["is_new_merchant"] == 1, "First purchase at this merchant"),
]


def reasons_for(row: dict, limit: int = 3) -> list[dict]:
    out = []
    for code, test, msg in REASON_RULES:
        try:
            if test(row):
                out.append({"code": code, "text": msg.format(**row)})
        except (KeyError, ValueError, TypeError):
            continue
        if len(out) >= limit:
            break
    return out
