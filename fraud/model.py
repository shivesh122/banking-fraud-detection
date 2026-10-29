"""
Two-stage fraud model

1. Isolation Forest (unsupervised): learns what normal transactions look like and gives every
   transaction an anomaly score. It needs no labels, so it can catch new fraud patterns.
2. Gradient Boosting (supervised): learns from confirmed fraud labels, using the engineered
   features *plus* the anomaly score.

Evaluation uses a time-based split (train on older months, test on the most recent 60 days),
which mirrors how the model would be used in production.
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, IsolationForest
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score, roc_curve

from .config import FEATURES, RECOVERY_RATE, REVIEW_COST, TEST_DAYS, WARMUP_DAYS

SEED = 42


def time_split(df: pd.DataFrame):
    start = df["timestamp"].min().normalize()
    end = df["timestamp"].max().normalize()
    warm = start + pd.Timedelta(days=WARMUP_DAYS)
    cut = end - pd.Timedelta(days=TEST_DAYS - 1)
    train = df[(df["timestamp"] >= warm) & (df["timestamp"] < cut)]
    test = df[df["timestamp"] >= cut]
    return train, test, {"train_start": str(warm.date()), "test_start": str(cut.date()), "end": str(end.date())}


def fit_isolation_forest(X: np.ndarray) -> IsolationForest:
    return IsolationForest(n_estimators=100, max_samples=256, random_state=SEED, n_jobs=-1).fit(X)


def anomaly_score(iforest: IsolationForest, X: np.ndarray) -> np.ndarray:
    """0..1, higher = more anomalous (sklearn's score_samples is negative)."""
    return -iforest.score_samples(X)


def fit_gbm(X: np.ndarray, y: np.ndarray) -> GradientBoostingClassifier:
    # Up-weight the rare fraud class so the model doesn't ignore it
    w = np.where(y == 1, (y == 0).sum() / max((y == 1).sum(), 1) * 0.25, 1.0)
    return GradientBoostingClassifier(
        n_estimators=200, max_depth=3, learning_rate=0.08, subsample=0.8, random_state=SEED
    ).fit(X, y, sample_weight=w)


def metrics_at(y, p, amount, thr):
    pred = p >= thr
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    tn = int((~pred & (y == 0)).sum())
    caught = float(amount[pred & (y == 1)].sum())
    missed = float(amount[~pred & (y == 1)].sum())
    return {
        "threshold": round(float(thr), 4),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
        "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
        "fpr": round(fp / (fp + tn), 5) if fp + tn else 0.0,
        "alerts": tp + fp,
        "fraud_amount_caught": round(caught, 0),
        "fraud_amount_missed": round(missed, 0),
        "net_savings": round(caught * RECOVERY_RATE - (tp + fp) * REVIEW_COST, 0),
    }


def best_threshold(y, p, amount) -> float:
    grid = np.unique(np.quantile(p, np.linspace(0.90, 0.99995, 400)))
    return float(max(grid, key=lambda t: metrics_at(y, p, amount, t)["net_savings"]))


def curve_points(y, p, kind: str, n=120):
    if kind == "roc":
        a, b, _ = roc_curve(y, p)
        keys = ("fpr", "tpr")
    else:
        # Interpolated precision (best precision achievable at >= each recall level) on an even recall grid
        prec, rec, _ = precision_recall_curve(y, p)
        grid = np.linspace(0, 1, 101)
        pts = []
        for r in grid:
            mask = rec >= r
            if mask.any():
                pts.append({"recall": round(float(r), 4), "precision": round(float(prec[mask].max()), 4)})
        return pts
    idx = np.unique(np.linspace(0, len(a) - 1, n).astype(int))
    return [{keys[0]: round(float(a[i]), 4), keys[1]: round(float(b[i]), 4)} for i in idx]


def threshold_table(y, p, amount):
    """Precomputed metrics for every threshold step so the dashboard slider is instant."""
    return [metrics_at(y, p, amount, t) for t in np.round(np.arange(0.02, 1.0, 0.01), 2)]


# ---------------------------------------------------------------- export for in-browser scoring
def _avg_path_length(n: int) -> float:
    """Average path length of an unsuccessful BST search, c(n), as used by Isolation Forest."""
    if n <= 1:
        return 0.0
    if n == 2:
        return 1.0
    return 2.0 * (np.log(n - 1.0) + np.euler_gamma) - 2.0 * (n - 1.0) / n


def _num(x: float) -> float:
    return float(f"{x:.9g}")


def _node_depths(tr) -> np.ndarray:
    depth = np.zeros(tr.node_count, dtype=int)
    for i in range(tr.node_count):
        for c in (tr.children_left[i], tr.children_right[i]):
            if c != -1:
                depth[c] = depth[i] + 1
    return depth


def _export_iforest_tree(est) -> dict:
    """Leaves store depth + c(n_leaf), the per-tree path length Isolation Forest averages."""
    tr = est.tree_
    depth = _node_depths(tr)
    leaf = tr.children_left == -1
    return {
        "f": tr.feature.tolist(),
        "t": [0 if lf else _num(th) for th, lf in zip(tr.threshold, leaf)],
        "l": tr.children_left.tolist(),
        "r": tr.children_right.tolist(),
        "v": [_num(depth[i] + _avg_path_length(int(tr.n_node_samples[i]))) if leaf[i] else 0 for i in range(tr.node_count)],
    }


def _export_gbm_tree(est) -> dict:
    tr = est.tree_
    leaf = tr.children_left == -1
    return {
        "f": tr.feature.tolist(),
        "t": [0 if lf else _num(th) for th, lf in zip(tr.threshold, leaf)],
        "l": tr.children_left.tolist(),
        "r": tr.children_right.tolist(),
        "v": [_num(v) if lf else 0 for v, lf in zip(tr.value[:, 0, 0], leaf)],
    }


def export_models(iforest: IsolationForest, gbm: GradientBoostingClassifier, threshold: float, path) -> dict:
    """Serialises both models to JSON; site/scorer.js reproduces sklearn's predictions from it."""
    init_raw = float(gbm._raw_predict_init(np.zeros((1, len(FEATURES) + 1)))[0, 0])
    payload = {
        "features": FEATURES + ["anomaly_score"],
        "threshold": threshold,
        "isolation_forest": {
            "c_max_samples": _avg_path_length(int(iforest.max_samples_)),
            "trees": [_export_iforest_tree(e) for e in iforest.estimators_],
        },
        "gbm": {
            "init": init_raw,
            "learning_rate": float(gbm.learning_rate),
            "trees": [_export_gbm_tree(e[0]) for e in gbm.estimators_],
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")))
    return payload


def train_and_evaluate(df: pd.DataFrame) -> dict:
    t0 = time.perf_counter()
    train, test, split = time_split(df)
    Xtr, Xte = train[FEATURES].to_numpy(float), test[FEATURES].to_numpy(float)
    ytr, yte = train["is_fraud"].to_numpy(int), test["is_fraud"].to_numpy(int)
    amt_te = test["amount"].to_numpy(float)

    iforest = fit_isolation_forest(Xtr)
    a_tr, a_te = anomaly_score(iforest, Xtr), anomaly_score(iforest, Xte)

    # Baseline: supervised model without the anomaly score
    gbm_plain = fit_gbm(Xtr, ytr)
    p_plain = gbm_plain.predict_proba(Xte)[:, 1]

    # Final: supervised model with the anomaly score as an extra feature
    Xtr2, Xte2 = np.column_stack([Xtr, a_tr]), np.column_stack([Xte, a_te])
    gbm = fit_gbm(Xtr2, ytr)
    p = gbm.predict_proba(Xte2)[:, 1]

    # Rule baseline a bank might start with
    rule = ((test["amount_ratio"] >= 5) | (test["txn_count_1h"] >= 3) | (test["distance_home_km"] >= 500)).to_numpy(float)

    def summary(name, score, thr=None):
        s = {"model": name, "roc_auc": round(roc_auc_score(yte, score), 4), "pr_auc": round(average_precision_score(yte, score), 4)}
        thr = best_threshold(yte, score, amt_te) if thr is None else thr
        s.update(metrics_at(yte, score, amt_te, thr))
        return s

    comparison = [
        summary("Rules (amount / velocity / distance)", rule, 0.5),
        summary("Isolation Forest (unsupervised)", a_te),
        summary("Gradient Boosting", p_plain),
        summary("Gradient Boosting + anomaly score (final)", p),
    ]
    thr = comparison[-1]["threshold"]

    # Permutation importance on all test frauds + a sample of legitimate transactions (fast, unbiased ranking)
    rng = np.random.default_rng(SEED)
    legit_idx = np.flatnonzero(yte == 0)
    idx = np.concatenate([np.flatnonzero(yte == 1), rng.choice(legit_idx, min(20000, len(legit_idx)), replace=False)])
    imp = permutation_importance(gbm, Xte2[idx], yte[idx], scoring="average_precision", n_repeats=3, random_state=SEED, n_jobs=-1)
    importance = sorted(
        ({"feature": f, "importance": round(float(m), 4)} for f, m in zip(FEATURES + ["anomaly_score"], imp.importances_mean)),
        key=lambda d: -d["importance"],
    )

    # recall by fraud pattern at the chosen threshold
    tt = test.assign(score=p, flagged=p >= thr)
    by_type = (
        tt[tt["is_fraud"] == 1].groupby("fraud_type").agg(frauds=("txn_id", "count"), caught=("flagged", "sum"), amount=("amount", "sum")).reset_index()
    )
    by_type["recall"] = (by_type["caught"] / by_type["frauds"]).round(3)

    return {
        "models": {"iforest": iforest, "gbm": gbm},
        "split": split | {"train_rows": len(train), "test_rows": len(test), "train_frauds": int(ytr.sum()), "test_frauds": int(yte.sum())},
        "comparison": comparison,
        "threshold": thr,
        "roc": {"final": curve_points(yte, p, "roc"), "iforest": curve_points(yte, a_te, "roc")},
        "pr": {"final": curve_points(yte, p, "pr"), "iforest": curve_points(yte, a_te, "pr")},
        "threshold_table": threshold_table(yte, p, amt_te),
        "importance": importance,
        "recall_by_type": json.loads(by_type.to_json(orient="records")),
        "train_seconds": round(time.perf_counter() - t0, 1),
    }


def score_all(df: pd.DataFrame, iforest, gbm) -> pd.DataFrame:
    X = df[FEATURES].to_numpy(float)
    a = anomaly_score(iforest, X)
    p = gbm.predict_proba(np.column_stack([X, a]))[:, 1]
    return df.assign(anomaly_score=a, fraud_probability=p)
