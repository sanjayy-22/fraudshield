# E2 — honest booking-time GBM

Score = mean of 5 LightGBM seeds, early-stopped on the 2017-H1 validation split (PR-AUC).
No leak / identifier column can enter: `assert_no_leak()` runs on every feature list.

## Test metrics
| model | scope | orders | fraud | base rate | ROC-AUC [95% CI] | PR-AUC [95% CI] | PR lift | recall @1% FPR | recall @5% FPR |
|---|---|---:|---:|---:|---|---|---:|---:|---:|
| honest GBM (with payment_type) | all | 13670 | 308 | 0.0225 | 0.880 [0.869, 0.890] | 0.093 [0.079, 0.110] | 4.11× | 0.045 | 0.237 |
| honest GBM (with payment_type) | transfer | 3784 | 308 | 0.0814 | 0.539 [0.507, 0.572] | 0.093 [0.081, 0.111] | 1.14× | 0.006 | 0.071 |
| honest GBM (no payment_type) | all | 13670 | 308 | 0.0225 | 0.533 [0.500, 0.564] | 0.025 [0.022, 0.030] | 1.12× | 0.013 | 0.065 |
| honest GBM (no payment_type) | transfer | 3784 | 308 | 0.0814 | 0.535 [0.504, 0.568] | 0.092 [0.079, 0.111] | 1.13× | 0.013 | 0.065 |

- honest GBM (with payment_type): best iterations 180 (seed 1); TRANSFER-scope ROC-AUC per seed 0.522, 0.530, 0.519, 0.548, 0.543
- honest GBM (no payment_type): best iterations 7 (seed 1); TRANSFER-scope ROC-AUC per seed 0.513, 0.540, 0.524, 0.518, 0.503

## Reading
- The **all-orders** ROC-AUC with payment_type is essentially the E1 rule: the model learned "TRANSFER".
- The **TRANSFER-scope** ROC-AUC 95% interval is [0.507, 0.572]. It only just excludes 0.5. The signal is weak but detectable. PR lift is 1.14×, which is operationally negligible (see E5 for the permutation test).
- Without payment_type, the all-orders ROC-AUC falls to about chance: payment type carries nearly all the signal.
- The bootstrap interval covers test-set sampling only; the per-seed spread above adds model variance on top.

## Feature importance — with payment_type (seed 1, SHAP on test)
| feature | gain_share | mean_abs_shap |
|---|---|---|
| is_transfer | 0.7844 | 2.7321 |
| order_region | 0.0288 | 0.0941 |
| discount_rate_mean | 0.0162 | 0.0496 |
| profit_total | 0.0158 | 0.0301 |
| profit_ratio_mean | 0.0142 | 0.0270 |
| cust_spend_ratio | 0.0135 | 0.0167 |
| main_category | 0.0126 | 0.0736 |
| cust_days_since_last | 0.0119 | 0.0298 |
| discount_total | 0.0117 | 0.0345 |
| cust_prior_spend | 0.0112 | 0.0275 |
| net_total | 0.0109 | 0.0750 |
| gross_sales | 0.0109 | 0.0822 |

## Feature importance — no payment_type (seed 1, SHAP on test)
| feature | gain_share | mean_abs_shap |
|---|---|---|
| net_total | 0.1638 | 0.1337 |
| profit_ratio_mean | 0.1356 | 0.0307 |
| discount_rate_mean | 0.0988 | 0.0445 |
| cust_prior_spend | 0.0936 | 0.0269 |
| discount_total | 0.0771 | 0.0216 |
| profit_total | 0.0696 | 0.0133 |
| n_units | 0.0556 | 0.0346 |
| gross_sales | 0.0507 | 0.0239 |
| order_hour | 0.0365 | 0.0180 |
| order_region | 0.0333 | 0.0080 |
| order_day | 0.0263 | 0.0136 |
| cust_orders_30d | 0.0255 | 0.0037 |

Importances of a model with ~chance-level ranking describe noise it fitted, not fraud drivers.
