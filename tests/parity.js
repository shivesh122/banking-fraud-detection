// Checks that site/scorer.js reproduces scikit-learn's scores. Usage: node tests/parity.js
const fs = require('fs');
const path = require('path');
const S = require('../site/scorer.js');
const root = path.join(__dirname, '..');
const model = JSON.parse(fs.readFileSync(path.join(root, 'site/model/model.json')));
const sample = JSON.parse(fs.readFileSync(path.join(root, 'data/processed/parity_sample.json')));
let maxA = 0, maxP = 0, flips = 0;
sample.X.forEach((x, i) => {
  const r = S.scoreVector(model, x);
  maxA = Math.max(maxA, Math.abs(r.anomaly_score - sample.anomaly[i]));
  maxP = Math.max(maxP, Math.abs(r.fraud_probability - sample.prob[i]));
  if ((r.fraud_probability >= model.threshold) !== (sample.prob[i] >= model.threshold)) flips += 1;
});
console.log(JSON.stringify({ rows: sample.X.length, max_anomaly_diff: maxA, max_probability_diff: maxP, decision_flips: flips }));
if (maxA > 1e-6 || maxP > 1e-6 || flips) process.exit(1);
