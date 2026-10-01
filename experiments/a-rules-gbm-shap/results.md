# Experiment A — rules + GBM + attributions

Stream: 21727 bookings, 243 fraud (1.12%). Time split at 2026-03-30: train 15209 / test 6518 (113 fraud in test).

## Ranking quality (test period)

| model                       |   auc |    ap |   recall_fpr1 |   recall_fpr05 |   thr_fpr1 |
|:----------------------------|------:|------:|--------------:|---------------:|-----------:|
| rules only                  | 0.881 | 0.764 |         0.761 |          0.761 |      0.000 |
| GBM behavioural features    | 0.989 | 0.870 |         0.867 |          0.805 |      0.004 |
| GBM all features (lightgbm) | 0.998 | 0.975 |         0.965 |          0.965 |      0.001 |
| GBM ⊕ rules (noisy-OR)      | 0.998 | 0.976 |         0.965 |          0.965 |      0.001 |

`recall_fpr1` = share of fraud caught when at most 1 % of legitimate bookings are flagged.

## Per-scenario recall at 1 % FPR (all-feature GBM)

| scenario             |   recall@1%FPR |     n |
|:---------------------|---------------:|------:|
| dormant_reactivation |           1.00 | 27.00 |
| geo_drift_heavy      |           1.00 |  8.00 |
| off_hours_new_device |           1.00 |  7.00 |
| payment_swap         |           1.00 | 16.00 |
| stealthy_mule        |           0.75 | 16.00 |
| velocity_burst       |           1.00 | 39.00 |

Loss prevented at 1 % FPR: ₹124,404 of ₹126,560 at risk (98%); 64 legitimate bookings flagged out of 6405.

## Top features by gain

|                   |   gain |
|:------------------|-------:|
| log_pay_age_min   |  20632 |
| drift_score       |   8901 |
| vel24_ratio       |   5367 |
| dev_shared_n      |   3301 |
| dest_addr_nov     |   3201 |
| w_z               |   2135 |
| cohort_individual |   2080 |
| dest_fraud        |   1507 |
| new_device        |    965 |
| log_value         |    950 |
| origin_nov        |    897 |
| dest_fanin_all    |    841 |
| hour              |    810 |
| log_n_hist        |    713 |
| val_z             |    485 |

## Observations

- Rules alone have high precision on the loud scenarios but miss the stealthy ones; they earn their keep as
  *hard blocks with reason codes* and as a safety net when the model is unavailable, not as the main detector.
- Adding graph + drift features to the behavioural GBM is where the stealthy-mule and payment-swap
  scenarios move (compare the two GBM rows and the per-scenario table).
- Attributions come from LightGBM's native `pred_contrib` (exact TreeSHAP values); no extra dependency.
- Profile poisoning: once the first fraudulent booking of a burst is absorbed into the shipper profile, later
  bookings of the same burst look 'seen'. The pipeline fixes this by quarantining held/blocked bookings from
  the profile until they are verified (see prototypes/fraudshield-pipeline).
