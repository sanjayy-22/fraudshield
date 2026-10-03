# FraudShield replay on real data: DataCo, 2017-07 → 2018-01

Training: 41763 orders (2015–2016). Calibration and conformal fit: 2017-H1, split in half.
Replay: 13670 orders (308 fraud), in time order, through the live path. Model `lightgbm-6d0ec8e2b84f`,
features `dataco-features-2026.10.1` (35 booking-time features, `assert_no_leak` passed).

## Ranking quality of the calibrated live model
| model | scope | orders | fraud | base rate | ROC-AUC [95% CI] | PR-AUC [95% CI] | PR lift | recall @1% FPR | recall @5% FPR |
|---|---|---:|---:|---:|---|---|---:|---:|---:|
| live RiskModel (calibrated) | all | 13670 | 308 | 0.0225 | 0.873 [0.863, 0.883] | 0.086 [0.075, 0.102] | 3.83× | 0.042 | 0.224 |
| live RiskModel (calibrated) | transfer | 3784 | 308 | 0.0814 | 0.511 [0.481, 0.545] | 0.086 [0.075, 0.106] | 1.06× | 0.013 | 0.045 |

## Policy comparison: same probabilities, same simulated outcomes
Fraud value at risk if everything is allowed: **200,026 USD**.

| policy | realised cost (USD) | fraud stopped | legit blocked | legit asked to verify | reviews | ALLOW/STEP_UP/HOLD/BLOCK |
|---|---:|---:|---:|---:|---:|---|
| allow all | 200,026 | 0/308 (0.0%) | 0 (0.00%) | 0 | 0 | 13670/0/0/0 |
| rule: step-up every TRANSFER | 122,499 | 242/308 (78.6%) | 97 (0.73%) | 3476 | 0 | 9886/3784/0/0 |
| fixed threshold @1% FPR | 236,817 | 7/308 (2.3%) | 58 (0.43%) | 0 | 0 | 13605/0/0/65 |
| two-threshold + review band | 211,181 | 11/308 (3.6%) | 23 (0.17%) | 0 | 109 | 13534/0/109/27 |
| cost-sensitive + conformal (live) | 94,736 | 211/308 (68.5%) | 39 (0.29%) | 1398 | 1363 | 10780/1527/1363/0 |

Conformal sets (α = 0.10) were ambiguous for 2131 of 13670 orders (15.6%). Only these
are eligible for analyst review under the live policy.

### Reading
- On this data every policy can only work on one fact: whether the order is TRANSFER. Inside TRANSFER
  the model's ranking is barely better than chance (see E2/E5), so the policies differ mainly in
  *what they do* with TRANSFER orders (allow, verify, review or block), not in *which* TRANSFER orders they pick.
- The costs depend on the stated assumptions (USD charge, LTV = max(2 × prior spend, order),
  analyst 5 USD, step-up pass rates from `CostParams`). Re-run with other values before quoting them.

## Explanations (top TreeSHAP log-odds contributions)
- Highest-scored **fraud** order (p = 0.176): `is_transfer`=1 (+5.42), `discount_rate_mean`=0.03 (+0.33), `cust_prior_spend`=1.25e+03 (+0.19), `order_hour`=5 (+0.18)
- Highest-scored **legitimate** order (p = 0.211): `is_transfer`=1 (+5.52), `order_day`=28 (+0.30), `n_units`=1 (+0.29), `discount_rate_mean`=0.02 (+0.24)

## Audit ledger
- Records: 13670; hash chain verified: **True**
- Tampering with record 5: verification **fails** at record 5
- Replay of `dataco-62477` from its stored feature vector: reproduced = **True**
