/*
 * In-browser fraud scorer. Re-implements the exported scikit-learn models:
 *   1. Isolation Forest anomaly score  = 2 ^ (-mean path length / c(max_samples))
 *   2. Gradient Boosting probability    = sigmoid(init + learning_rate * sum(tree outputs))
 * Inputs are cast to float32 (Math.fround) exactly like scikit-learn's tree predictors.
 * Works in the browser (window.FraudScorer) and in Node (module.exports) for parity tests.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.FraudScorer = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const HIGH_RISK = new Set(['Electronics', 'Jewellery', 'Gift Cards', 'Gaming & Crypto']);

  function leafValue(tree, x) {
    let node = 0;
    while (tree.l[node] !== -1) {
      node = Math.fround(x[tree.f[node]]) <= tree.t[node] ? tree.l[node] : tree.r[node];
    }
    return tree.v[node];
  }

  function anomalyScore(model, x) {
    const trees = model.isolation_forest.trees;
    let total = 0;
    for (let i = 0; i < trees.length; i += 1) total += leafValue(trees[i], x);
    const mean = total / trees.length;
    return Math.pow(2, -mean / model.isolation_forest.c_max_samples);
  }

  function fraudProbability(model, x) {
    const g = model.gbm;
    let raw = g.init;
    for (let i = 0; i < g.trees.length; i += 1) raw += g.learning_rate * leafValue(g.trees[i], x);
    return 1 / (1 + Math.exp(-raw));
  }

  /** Scores a feature vector ordered as model.features (without anomaly_score). */
  function scoreVector(model, base) {
    const a = anomalyScore(model, base);
    const p = fraudProbability(model, base.concat([a]));
    return { anomaly_score: a, fraud_probability: p, is_alert: p >= model.threshold };
  }

  /** Builds the feature dictionary from the human-friendly form inputs on the Score page. */
  function featuresFromInput(inp) {
    const amount = Math.max(+inp.amount || 0, 1);
    const usual = Math.max(+inp.usual_amount || 1, 1);
    const mins = Math.max(+inp.mins_since_last || 0, 0);
    const hours = Math.max(mins / 60, 0.25);
    const distLast = Math.max(+inp.distance_last_km || 0, 0);
    const hour = Math.min(Math.max(Math.round(+inp.hour || 0), 0), 23);
    return {
      log_amount: Math.log1p(amount),
      amount_ratio: amount / usual,
      amount_24h_ratio: Math.max(+inp.spent_24h || 0, 0) / usual,
      txn_count_1h: Math.max(+inp.txn_count_1h || 0, 0),
      txn_count_24h: Math.max(+inp.txn_count_24h || 0, 0),
      log_mins_since_last: Math.log1p(mins),
      hour,
      is_night: hour < 6 || hour >= 23 ? 1 : 0,
      distance_home_km: Math.max(+inp.distance_home_km || 0, 0),
      speed_kmh: Math.min(distLast / hours, 5000),
      is_new_device: inp.new_device ? 1 : 0,
      is_new_merchant: inp.new_merchant ? 1 : 0,
      is_online: inp.channel === 'Online' ? 1 : 0,
      is_upi: inp.channel === 'UPI' ? 1 : 0,
      is_atm: inp.channel === 'ATM' ? 1 : 0,
      is_pos: inp.channel === 'POS' ? 1 : 0,
      is_high_risk_category: HIGH_RISK.has(inp.category) ? 1 : 0,
      is_international: inp.international ? 1 : 0,
      account_age_days: Math.max(+inp.account_age_days || 0, 0),
    };
  }

  // Same rules as fraud/reasons.py
  const fmt1 = (v) => v.toFixed(1);
  const fmt0 = (v) => Math.round(v).toLocaleString('en-IN');
  const RULES = [
    ['NEW_DEVICE', (r) => r.is_new_device === 1, () => 'Payment from a device first seen in the last 48 hours'],
    ['AMOUNT_SPIKE', (r) => r.amount_ratio >= 5, (r) => `Amount is ${fmt1(r.amount_ratio)}× the customer's usual spend`],
    ['VELOCITY_1H', (r) => r.txn_count_1h >= 3, (r) => `${fmt0(r.txn_count_1h)} other transactions in the past hour`],
    ['BURST_24H', (r) => r.amount_24h_ratio >= 6, (r) => `Spent ${fmt1(r.amount_24h_ratio)}× usual amount in the past 24 hours`],
    ['IMPOSSIBLE_TRAVEL', (r) => r.speed_kmh >= 500, (r) => `Implied travel speed of ${fmt0(r.speed_kmh)} km/h since last transaction`],
    ['FAR_FROM_HOME', (r) => r.distance_home_km >= 500, (r) => `${fmt0(r.distance_home_km)} km from the customer's home city`],
    ['NIGHT', (r) => r.is_night === 1, () => 'Made between 11 pm and 6 am'],
    ['HIGH_RISK_MCC', (r) => r.is_high_risk_category === 1, () => 'High-risk merchant category'],
    ['RAPID_REPEAT', (r) => r.log_mins_since_last <= 1.8, () => 'Less than 5 minutes after the previous transaction'],
    ['NEW_MERCHANT', (r) => r.is_new_merchant === 1, () => 'First purchase at this merchant'],
  ];

  function reasons(feat, limit = 3) {
    const out = [];
    for (const [code, test, msg] of RULES) {
      if (test(feat)) out.push({ code, text: msg(feat) });
      if (out.length >= limit) break;
    }
    return out;
  }

  function score(model, input) {
    const feat = featuresFromInput(input);
    const vec = model.features.filter((f) => f !== 'anomaly_score').map((f) => feat[f]);
    return Object.assign(scoreVector(model, vec), { features: feat, reasons: reasons(feat, 5) });
  }

  return { anomalyScore, fraudProbability, scoreVector, featuresFromInput, reasons, score };
});
