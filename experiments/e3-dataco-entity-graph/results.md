# E3 — entity-graph counters

Counters (all label-delayed by 1 day, strictly earlier orders): `city_orders_7d`, `city_fraud_30d`,
`city_fraud_rate_90d`, `product_fraud_30d`, `product_fraud_rate_90d`, `custcity_fraud_90d`.

## Homophily check (train + valid + test, TRANSFER only)
If fraud were organised around shared entities, the "with" rate would clearly exceed the "without" rate.

| linked entity signal (TRANSFER orders) | orders with signal | fraud rate with | fraud rate without | ratio |
|---|---:|---:|---:|---:|
| destination city had fraud in last 30 d | 3755 | 0.0842 | 0.0818 | 1.03 |
| destination city fraud rate (90 d) in top decile | 4216 | 0.0809 | 0.0828 | 0.98 |
| main product had ≥ median fraud in last 30 d | 10557 | 0.0812 | 0.0839 | 0.97 |
| customer home city fraud (90 d) in top decile | 1834 | 0.0840 | 0.0821 | 1.02 |
| customer had a prior fraud order | 782 | 0.0754 | 0.0826 | 0.91 |
| customer had a prior canceled order | 724 | 0.0787 | 0.0825 | 0.95 |

## Test metrics
| model | scope | orders | fraud | base rate | ROC-AUC [95% CI] | PR-AUC [95% CI] | PR lift | recall @1% FPR | recall @5% FPR |
|---|---|---:|---:|---:|---|---|---:|---:|---:|
| GBM + entity counters (with payment_type) | all | 13670 | 308 | 0.0225 | 0.872 [0.862, 0.882] | 0.083 [0.072, 0.098] | 3.70× | 0.039 | 0.227 |
| GBM + entity counters (with payment_type) | transfer | 3784 | 308 | 0.0814 | 0.508 [0.479, 0.537] | 0.083 [0.073, 0.097] | 1.02× | 0.000 | 0.058 |
| GBM + entity counters (no payment_type) | all | 13670 | 308 | 0.0225 | 0.508 [0.472, 0.541] | 0.027 [0.022, 0.036] | 1.18× | 0.026 | 0.071 |
| GBM + entity counters (no payment_type) | transfer | 3784 | 308 | 0.0814 | 0.508 [0.476, 0.541] | 0.097 [0.081, 0.123] | 1.19× | 0.023 | 0.075 |

- GBM + entity counters (with payment_type): TRANSFER-scope ROC-AUC per seed 0.506, 0.500, 0.496, 0.500, 0.509
- GBM + entity counters (no payment_type): TRANSFER-scope ROC-AUC per seed 0.507, 0.499, 0.521, 0.498, 0.485
