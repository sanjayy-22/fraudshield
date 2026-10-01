# Comparison — four detector architectures on one simulated stream

All numbers: `simulate.py` with seed 7 (21,727 bookings, 243 fraud in 70 episodes across
6 rings), time split at the 70th percentile (test: 6,518 bookings, 113 fraud). They describe
the simulator and are meaningful for **relative** comparison only.

## Head-to-head

| Approach | Needs labels | AUC | AP | Recall @ 1 % FPR | Stealthy-mule recall | Serving cost / booking | Explains as |
|----------|:-----------:|----:|---:|-----------------:|---------------------:|------------------------|-------------|
| A · Rules only | no (analyst knowledge) | 0.881 | 0.764 | 0.76 | — | µs | reason codes |
| A · GBM, behavioural features | yes | 0.989 | 0.870 | 0.87 | — | ~1 ms | SHAP |
| B · GBM, graph features only | yes (+ delayed labels) | 0.947 | 0.922 | 0.92 | 0.75 | 3 hash lookups + 1 union-find | shared-entity facts |
| C · Drift score, cohort back-off | **no** | 0.968 | 0.492 | 0.56 | 0.25 | µs | "vs your own history" |
| A+B+C · GBM, all features | yes | **0.998** | **0.975** | **0.96** | 0.75 | ~2 ms | SHAP + facts |
| A+B+C ⊕ rules (noisy-OR) | yes | 0.998 | 0.976 | 0.96 | 0.75 | ~2 ms | both |

Cold start (drift score AUC on bookings with 0–4 prior bookings): 0.95 with cohort back-off vs
0.82 without (exp. C). Unsupervised mule-address discovery: precision@10 0.5 for naive fan-in
(hubs dominate) vs 1.0 for novelty-mass (exp. B).

## What each experiment revealed

**A — rules + GBM.** Rules are precise on loud scenarios (velocity bursts, dormant reactivation,
new-card-plus-express) and blind to the stealthy one. A GBM on behavioural features alone
already beats rules, but the jump from 0.87 to 0.96 recall comes from adding the graph and
drift families — the detectors are complementary, not redundant. First version of the simulator
gave AUC 1.000, which was a leak-shaped warning: rings never rotated infrastructure, so
"address has confirmed fraud" was a perfect separator. Rotation and legitimate look-alikes were
added before anything else was measured.

**B — entity graph.** 83 % of live-period fraud touches infrastructure already confirmed bad —
label propagation alone is a strong detector once the feedback loop exists. Raw fan-in is a trap
(fulfilment hubs); the fix is weighting fan-in by how *surprising* the destination was for each
shipper, plus a degree cap so hubs never merge components. Two feedback-hygiene bugs surfaced
here and were fixed in the feature store: (1) confirming fraud must not burn the victim's own
device/card (cascaded to 11 % of legitimate bookings blocked), (2) cumulative counters drift
upward over months and push the tree model outside its training range.

**C — behavioural drift.** A label-free score with hand-set weights reaches AUC 0.968 but only
0.56 recall at 1 % FPR: it ranks fraud high but its top decile is crowded with legitimate
novelty (new customers, sale days). Its value is (i) cold start, (ii) survival when labels are
absent or tactics change, (iii) the most human explanation. Fed to the GBM as a feature it is the
second most important feature by gain.

**D — grounded explanation.** The verifier (numbers + identifiers ⊆ evidence pack) is trivial
and sufficient for the failure mode that matters (invented facts). Counterfactuals fall out of
the model for free (re-score with one feature set to the shipper's typical value) and convert an
attribution into a verification task. The LLM adds fluency, not information; the template
proves the contract without an API key.

**Pipeline (A+B+C + decision engine).** Same probabilities, three policies:

| Policy | Realised cost | Fraud stopped | Legit blocked | Reviews |
|--------|--------------:|:-------------:|:-------------:|:-------:|
| cost-sensitive (live) | **₹57,802** | 107/113 | 19 (0.30 %) | 0 |
| fixed threshold @ 1 % FPR | ₹566,881 | 110/113 | 74 (1.16 %) | 0 |
| two-threshold + review band | ₹349,803 | 110/113 | 44 (0.69 %) | 96 |
| no detection | ₹126,560 | 0/113 | 0 | 0 |

Under the assumed cost model (5 % churn on a blocked legitimate customer, LTV by cohort), a
threshold policy that catches slightly more fraud is *worse than doing nothing*; the
cost-sensitive policy stops 95 % of fraud at a quarter of the friction. Calibration turned out to
be load-bearing: isotonic regression on ~40 calibration fraud cases produced 0/1 plateaus that
made every threshold policy degenerate (block everything); Platt scaling fixed it.

## Trade-offs

| Dimension | Rules | GBM | Graph | Drift |
|-----------|-------|-----|-------|-------|
| Detection power | low–medium | high | high (organised fraud) | medium |
| Needs labels | no | yes | delayed labels help a lot | no |
| Adapts to new tactics | when analysts write rules | after retrain | immediately via propagation | immediately |
| Cold start | n/a | weak | weak (no edges yet) | strong with back-off |
| Explainability | perfect | SHAP (needs translation) | concrete facts | concrete facts |
| Serving cost | µs | ms | µs (counters) | µs |
| Failure mode | blind spots | drift, leakage | super-nodes, poisoning | hand-set weights |

## Convergence

Ship **A+B+C fused at feature level under one calibrated GBM, rules as hard overrides, the
cost-sensitive decision engine, conformal-gated review, the grounded explainer and the ledger** —
i.e. `prototypes/fraudshield-pipeline/`. Keep the drift score as the standalone fallback when the
model or labels are unavailable. Treat the simulator as part of the product (adversarial
evaluation), not as throw-away test data.

Recommended next experiments: `notes/next-experiments.md`.
