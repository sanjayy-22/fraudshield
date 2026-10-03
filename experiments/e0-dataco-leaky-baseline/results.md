# E0 — leaky baseline (NOT deployable)

Post-booking columns added on top of the honest feature set: `leak_canceled` (delivery_status =
'Shipping canceled'), `leak_late_risk` (late_delivery_risk), `leak_days_real` (days_shipping_real),
`leak_delay_minus_sched`. `order_status` itself is excluded (it *is* the label).

## Split
| split | from | to | orders | fraud orders |
|---|---|---|---:|---:|
| train | 2015-01-01 | 2016-12-31 | 41763 | 941 |
| valid | 2017-01-01 | 2017-06-30 | 10319 | 239 |
| test | 2017-07-01 | 2018-01-31 | 13670 | 308 |

## Test metrics
| model | scope | orders | fraud | base rate | ROC-AUC [95% CI] | PR-AUC [95% CI] | PR lift | recall @1% FPR | recall @5% FPR |
|---|---|---:|---:|---:|---|---|---:|---:|---:|
| leaky: honest + post-booking columns | all | 13670 | 308 | 0.0225 | 0.990 [0.988, 0.991] | 0.529 [0.476, 0.583] | 23.50× | 0.481 | 1.000 |
| leaky: honest + post-booking columns | transfer | 3784 | 308 | 0.0814 | 0.960 [0.954, 0.965] | 0.529 [0.477, 0.590] | 6.50× | 0.107 | 0.643 |
| leaky: post-booking columns only | all | 13670 | 308 | 0.0225 | 0.988 [0.987, 0.990] | 0.497 [0.451, 0.541] | 22.07× | 0.000 | 1.000 |
| leaky: post-booking columns only | transfer | 3784 | 308 | 0.0814 | 0.955 [0.949, 0.961] | 0.497 [0.453, 0.546] | 6.11× | 0.000 | 0.000 |

## Why it looks so good: `delivery_status` by fraud (all orders)
| delivery_status | orders | fraud orders | fraud rate |
|---|---:|---:|---:|
| Advance shipping | 15127 | 0 | 0.000 |
| Late delivery | 36048 | 0 | 0.000 |
| Shipping canceled | 2855 | 1488 | 0.521 |
| Shipping on time | 11722 | 0 | 0.000 |

Every fraud order is 'Shipping canceled'. The only other orders with that status are the
CANCELED ones, so this one post-event column narrows fraud to roughly a 50/50 group.

## Top features — leaky: honest + post-booking columns
| feature | gain_share | mean_abs_shap |
|---|---|---|
| leak_canceled | 0.9164 | 0.7925 |
| is_transfer | 0.0589 | 0.3400 |
| leak_late_risk | 0.0134 | 0.1339 |
| discount_total | 0.0010 | 0.0024 |
| cust_days_since_last | 0.0009 | 0.0058 |
| discount_rate_mean | 0.0008 | 0.0053 |
| profit_total | 0.0008 | 0.0042 |
| order_region | 0.0008 | 0.0090 |
| cust_spend_ratio | 0.0007 | 0.0021 |
| order_hour | 0.0007 | 0.0028 |
| gross_sales | 0.0007 | 0.0019 |
| order_day | 0.0006 | 0.0031 |

**Conclusion.** The ~0.99 AUC is the leak, not detection. In a booking-time system none of these columns exist yet.
