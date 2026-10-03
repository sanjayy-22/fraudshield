# E4 — unsupervised anomaly

Scores are added to the TRANSFER indicator (scaled so the rule dominates), so in the all-orders
scope they only re-rank within each payment group; the TRANSFER-scope row is the pure anomaly ranking.

## Test metrics
| model | scope | orders | fraud | base rate | ROC-AUC [95% CI] | PR-AUC [95% CI] | PR lift | recall @1% FPR | recall @5% FPR |
|---|---|---:|---:|---:|---|---|---:|---:|---:|
| IsolationForest × TRANSFER gate | all | 13670 | 308 | 0.0225 | 0.873 [0.865, 0.882] | 0.086 [0.075, 0.100] | 3.82× | 0.052 | 0.211 |
| IsolationForest × TRANSFER gate | transfer | 3784 | 308 | 0.0814 | 0.512 [0.478, 0.546] | 0.086 [0.076, 0.102] | 1.06× | 0.006 | 0.058 |
| customer drift × TRANSFER gate | all | 13670 | 308 | 0.0225 | 0.871 [0.863, 0.880] | 0.083 [0.074, 0.097] | 3.67× | 0.036 | 0.195 |
| customer drift × TRANSFER gate | transfer | 3784 | 308 | 0.0814 | 0.506 [0.481, 0.534] | 0.083 [0.073, 0.098] | 1.02× | 0.010 | 0.042 |

An ROC-AUC near 0.5 in the TRANSFER scope means fraudulent orders are no more anomalous than legitimate ones
on these features.
