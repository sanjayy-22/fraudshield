# E1 — rule only: flag TRANSFER

## Fraud by payment type (all orders, 2015-01 → 2018-01)
| payment_type | orders | fraud orders | fraud rate |
|---|---:|---:|---:|
| CASH | 7249 | 0 | 0.0000 |
| DEBIT | 25340 | 0 | 0.0000 |
| PAYMENT | 15086 | 0 | 0.0000 |
| TRANSFER | 18077 | 1488 | 0.0823 |

## payment_type × order_status (orders)
Each status occurs under exactly one payment type, so `payment_type` looks like it was generated from
the status. It may well be known at booking time in a real system, but treat any signal in it with suspicion.

| order_status | CASH | DEBIT | PAYMENT | TRANSFER |
|---|---:|---:|---:|---:|
| CANCELED | 0 | 0 | 0 | 1367 |
| CLOSED | 7249 | 0 | 0 | 0 |
| COMPLETE | 0 | 21716 | 0 | 0 |
| ON_HOLD | 0 | 3624 | 0 | 0 |
| PAYMENT_REVIEW | 0 | 0 | 704 | 0 |
| PENDING | 0 | 0 | 0 | 7321 |
| PENDING_PAYMENT | 0 | 0 | 14382 | 0 |
| PROCESSING | 0 | 0 | 0 | 7901 |
| SUSPECTED_FRAUD | 0 | 0 | 0 | 1488 |

## Test metrics
| model | scope | orders | fraud | base rate | ROC-AUC [95% CI] | PR-AUC [95% CI] | PR lift | recall @1% FPR | recall @5% FPR |
|---|---|---:|---:|---:|---|---|---:|---:|---:|
| rule: payment_type == TRANSFER | all | 13670 | 308 | 0.0225 | 0.870 [0.866, 0.874] | 0.081 [0.073, 0.090] | 3.61× | 0.000 | 0.000 |
| rule: payment_type == TRANSFER | transfer | 3784 | 308 | 0.0814 | 0.500 [0.500, 0.500] | 0.081 [0.073, 0.091] | 1.00× | 0.000 | 0.000 |

On the test window the rule flags 3784 of 13670 orders (27.7%) and catches
308 of 308 frauds (100%). Precision is 0.081.
