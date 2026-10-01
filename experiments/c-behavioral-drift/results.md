# Experiment C — behavioural drift with cohort back-off

## Ranking quality (test period)

| model                                       |   auc |    ap |   recall_fpr1 |    n |   fraud |
|:--------------------------------------------|------:|------:|--------------:|-----:|--------:|
| drift score, cohort back-off (unsupervised) | 0.968 | 0.492 |         0.558 | 6518 |     113 |
| drift score, per-shipper only (no back-off) | 0.967 | 0.429 |         0.522 | 6518 |     113 |
| supervised GBM, all features (reference)    | 0.998 | 0.975 |         0.965 | 6518 |     113 |

## Cold start: AUC by amount of shipper history at booking time

| history      |   AUC back-off |   AUC no back-off |   AUC GBM |    n |   fraud |
|:-------------|---------------:|------------------:|----------:|-----:|--------:|
| 0–4 bookings |          0.952 |             0.822 |     1.000 |   55 |       8 |
| 5–29         |          0.969 |             0.974 |     1.000 |  580 |      38 |
| 30+          |          0.968 |             0.969 |     0.997 | 5883 |      67 |

## Per-scenario recall of the unsupervised drift score at 1 % FPR

| scenario             |   recall@1%FPR (drift) |
|:---------------------|-----------------------:|
| dormant_reactivation |                   0.70 |
| geo_drift_heavy      |                   0.88 |
| off_hours_new_device |                   0.86 |
| payment_swap         |                   0.75 |
| stealthy_mule        |                   0.25 |
| velocity_burst       |                   0.38 |

## Which drift terms separate (test period means)

|                    |   legit mean |   fraud mean |   ratio |
|:-------------------|-------------:|-------------:|--------:|
| |w_z|              |         0.78 |         1.51 |    1.94 |
| |val_z|            |         0.81 |         1.36 |    1.68 |
| dest_city_nov      |         2.10 |         3.74 |    1.78 |
| dest_addr_nov      |         2.67 |         8.51 |    3.19 |
| service_nov        |         0.93 |         1.24 |    1.33 |
| hour_nov           |         2.66 |         3.71 |    1.40 |
| origin_nov         |         0.36 |         1.43 |    3.99 |
| log1p(vel24_ratio) |         0.62 |         1.39 |    2.25 |
| new_device         |         0.04 |         0.57 |   14.99 |
| new_payment        |         0.02 |         0.40 |   21.80 |

## Observations

- With zero labels the profile-drift score already ranks fraud well above legitimate traffic; it is the
  detector that keeps working when fraud tactics change and labels have not caught up.
- Cohort back-off is what makes the first few bookings of a shipper scoreable at all: without it, z-scores
  and novelty terms are undefined/zero for thin histories, which is exactly where dormant/new accounts sit.
- The weights are hand-set. In the pipeline the drift score is fed to the GBM as one feature, so the
  supervised model re-weights it; standalone it is the fallback when the model is unavailable.
- Everything here is O(1) per booking against a per-shipper hash (counts, Welford moments, a 7-day deque):
  it maps directly onto a Redis hash per shipper.
