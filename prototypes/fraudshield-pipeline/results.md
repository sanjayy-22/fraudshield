# FraudShield pipeline — live replay results

History: 15209 bookings → model `lightgbm-daf7f63190d7` (train 10646, 84 fraud; Platt calibration on 2281; conformal on 2282). Live stream: 6518 bookings, 113 fraud, from 2026-03-30 to 2026-05-04.

Fraud loss at risk if nothing is detected: **₹126,560** (charge × 1.6 over all fraud bookings).

## Policy comparison (same probabilities, realised cost with true labels)

| policy                      |   realised cost ₹ | fraud stopped   |   fraud stopped % |   legit blocked |   legit blocked % |   legit asked to verify |   reviews | ALLOW/STEP_UP/HOLD/BLOCK   |
|:----------------------------|------------------:|:----------------|------------------:|----------------:|------------------:|------------------------:|----------:|:---------------------------|
| cost-sensitive (live)       |             57802 | 107/113         |              94.7 |              19 |              0.3  |                       1 |         0 | 6391/5/0/122               |
| fixed threshold @1% FPR     |            566881 | 110/113         |              97.3 |              74 |              1.16 |                       0 |         0 | 6334/0/0/184               |
| two-threshold + review band |            349803 | 110/113         |              97.3 |              44 |              0.69 |                       0 |        96 | 6269/0/96/153              |

Realised cost includes fraud that shipped, revenue and churn from blocking legitimate customers, step-up friction, and analyst time. Lower is better.

## Recall by fraud scenario (live policy, stopped before shipping)

| scenario             |   stopped |   n |   recall |
|:---------------------|----------:|----:|---------:|
| dormant_reactivation |        26 |  27 |     0.96 |
| geo_drift_heavy      |         8 |   8 |     1    |
| off_hours_new_device |         7 |   7 |     1    |
| payment_swap         |        16 |  16 |     1    |
| stealthy_mule        |        11 |  16 |     0.69 |
| velocity_burst       |        39 |  39 |     1    |

## Same probability, different customer → different action

Live policy at each fraud probability, by shipment charge and customer value (no hard rule, review capacity available):

| charge   |    p | individual   | sme     | ecommerce   |
|:---------|-----:|:-------------|:--------|:------------|
| ₹3,000   | 0.02 | ALLOW        | ALLOW   | ALLOW       |
| ₹3,000   | 0.1  | HOLD         | HOLD    | ALLOW       |
| ₹3,000   | 0.3  | HOLD         | HOLD    | HOLD        |
| ₹3,000   | 0.6  | HOLD         | HOLD    | HOLD        |
| ₹3,000   | 0.9  | BLOCK        | HOLD    | HOLD        |
| ₹3,000   | 0.99 | BLOCK        | BLOCK   | BLOCK       |
| ₹300     | 0.02 | ALLOW        | ALLOW   | ALLOW       |
| ₹300     | 0.1  | STEP_UP      | ALLOW   | ALLOW       |
| ₹300     | 0.3  | STEP_UP      | STEP_UP | ALLOW       |
| ₹300     | 0.6  | STEP_UP      | STEP_UP | ALLOW       |
| ₹300     | 0.9  | BLOCK        | STEP_UP | STEP_UP     |
| ₹300     | 0.99 | BLOCK        | BLOCK   | STEP_UP     |

## Latency of the synchronous path (features + rules + model + conformal + decision + ledger write)

p50 3.22 ms · p95 5.36 ms · p99 6.44 ms · max 13.35 ms (single Python process, in-memory store; no network hops).

## Audit ledger

- chain valid: **True** over 6518 records; tampering one field of record 5 is detected: **True** (chain breaks at record 5)
- replay of `B015209`: stored p = 0.000000, re-scored p = 0.000000, reproduced = **True**

## Sample explanations (generated off the decision path, verified for grounding)

### caught fraud (BLOCK) — B015253 (p = 1.000, BLOCK, true: fraud)

**Analyst:** Booking B015253 by shipper S0059 (sme) has a calibrated fraud probability of 1.000; action taken: BLOCK. The shipper has 27 prior bookings on record. Main drivers — behavioural drift vs own history: 10.3 (typical ≈ 4); payment instrument age: 0.4 h old; other shippers on this device (30 d): 1; other shippers to this address (30 d): 1. Policy rules triggered: R01_NEW_PAY_NEW_DEST_EXPRESS (payment instrument added <60 min ago + never-seen destination + express/priority); R04_KNOWN_MULE_DEST (destination address linked to ≥2 confirmed fraud shipments); R05_SHARED_FRAUD_DEVICE (device previously used on confirmed-fraud bookings, new to this shipper); R07_OFFHOURS_NEW_DEVICE_NEW_DEST (booked 00:00–05:00 from a new device to a new destination). Linked infrastructure: destination address has 3 confirmed-fraud shipments, device 2, payment instrument 0.

**Customer:** We were unable to process booking B015253. Please contact support with this reference so we can assist you.

Grounding verifier: PASS

### fraud sent to step-up — B015348 (p = 0.539, STEP_UP, true: fraud)

**Analyst:** Booking B015348 by shipper S0059 (sme) has a calibrated fraud probability of 0.539; action taken: STEP_UP. The shipper has 27 prior bookings on record. Main drivers — behavioural drift vs own history: 10.3 (typical ≈ 4); payment instrument age: 0.7 h old; destination novelty for this shipper: 10.7 nats; weight vs shipper's history: +0.8 σ. Policy rules triggered: R01_NEW_PAY_NEW_DEST_EXPRESS (payment instrument added <60 min ago + never-seen destination + express/priority). It would score below threshold (0.000) if the behavioural drift vs own history were at this shipper's typical level — that is the first thing to verify with the account owner. The model's conformal prediction set is ambiguous, so human review is worth its cost here.

**Customer:** To protect your account, please confirm booking B015348 using the verification link we sent to your registered contact details. This takes under a minute.

Grounding verifier: PASS

## Notes

- The live policy's HOLD is gated by the conformal prediction set: analysts only see bookings the model
  declares ambiguous at 90 % confidence, so the review budget is spent where it changes outcomes.
- Feedback closes the loop immediately: a failed step-up is a confirmed-fraud label within a day, blocked
  bookings never poison the shipper's behavioural profile, and the graph learns the mule address at once.
- Challenger policies are scored in shadow on the same probabilities — the champion/challenger mechanism
  a production system would use to roll out a new policy version safely.
