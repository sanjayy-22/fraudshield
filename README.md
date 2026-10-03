# FraudShield — early detection of fraudulent shipping bookings

Booking-time fraud screening for a parcel carrier: decide **ALLOW / STEP-UP / HOLD / BLOCK** in
milliseconds, explain it in plain language, and record it in a tamper-evident ledger.

```
notes/         framing, target architecture, novelty pitch, comparison, next experiments
visuals/       architecture diagram (svg/html), ring graph, replay dashboard
prototypes/
  data/        simulate.py   synthetic booking stream with ATO fraud rings (no real data needed)
               featurize.py  point-in-time online feature store (behaviour, velocity, identity, graph)
               clean_dataco.py     raw DataCo Supply Chain CSV → cleaned_dataco.csv
               dataco_features.py  real-data feature contract (leak columns banned) + point-in-time history
               dataco_protocol.py  time split, metrics with bootstrap CIs, shared LightGBM
  fraudshield-pipeline/      end-to-end prototype: rules ⊕ calibrated GBM ⊕ drift ⊕ graph
                             → conformal set → cost-sensitive decision → audit ledger → explanation
                             demo.py (replay + policy comparison + dashboard), api.py (FastAPI)
experiments/
  a-rules-gbm-shap/          supervised tabular detector + attributions
  b-entity-graph/            ring / mule detection, feature-group ablation, ring picture
  c-behavioral-drift/        unsupervised per-shipper fingerprint, cold start
  d-grounded-explanation/    evidence pack → narrative → hallucination verifier → counterfactuals
  e0…e5-dataco-*/            real DataCo data: leaky baseline, rule, honest GBM, entity graph, anomaly, label-shuffle null
tests/                       leakage + point-in-time tests for the DataCo features
```

## Run

```bash
pip install numpy pandas scikit-learn lightgbm networkx matplotlib fastapi uvicorn tabulate
python3 experiments/a-rules-gbm-shap/run.py        # writes results.md, model.pkl
python3 experiments/b-entity-graph/run.py          # writes results.md, visuals/ring_graph.png
python3 experiments/c-behavioral-drift/run.py
python3 experiments/d-grounded-explanation/run.py  # needs model.pkl from A
python3 prototypes/fraudshield-pipeline/demo.py    # writes results.md, stats.json, ledger.jsonl, visuals/dashboard.html
python3 visuals/make_architecture.py

# real data (DataCo): needs prototypes/data/cleaned_dataco.csv
python3 -m pytest tests/ -q
for e in experiments/e*-dataco-*/; do python3 $e/run.py; done
python3 prototypes/fraudshield-pipeline/demo_dataco.py   # writes results_dataco.md, stats_dataco.json, visuals/dashboard_dataco.html
python3 visuals/make_dataco_charts.py
cd prototypes/fraudshield-pipeline && uvicorn api:app --port 8080   # POST /score, GET /explain/{id}, POST /feedback
```

## Guided demo (start here for a presentation)

Start the backend and frontend (commands below), open http://127.0.0.1:5173 and press **Run the whole demo** on the
**Guided demo** tab. Six chapters run real orders through the system, and each step says who decided:

| # | Chapter | Shows |
|---|---|---|
| 1 | The ML model on its own | the LightGBM model decides alone: card → approved, bank transfer → team review, discounted transfer → verify |
| 2 | One rule at a time | expert rules and their weights: burst → verify, new card → review, known fraud address → stopped |
| 3 | Rules add up | three medium rules: 70% → 88% → 92.8%, past the 85% fraud line |
| 4 | People in the loop, and learning | analyst rejects an order → its card is known fraud → another customer's order with it is stopped |
| 5 | Verification | wrong code, then right code → approved with tracking number |
| 6 | Explain and audit | plain-language (AI or standard) explanation and the hash-chained audit-log check |

**Reset** returns to a clean state (clock 2018-02-01 09:00, no orders, no known fraud), so every run gives the same
results. The system has two scoring layers: an ML model trained on real DataCo orders, and expert-weighted rules for
signals the dataset doesn't contain (device, card age, weight, address, bursts).

## Booking desk demo (model → backend → frontend)

```bash
python3 prototypes/fraudshield-pipeline/train_dataco.py        # 1. model: train once → models/dataco/ (already committed)
cd prototypes/fraudshield-pipeline
uvicorn api_dataco:app --port 8081                             # 2. backend (terminal 1), loads the saved model
python3 -m http.server 5173 --directory ../../frontend         # 3. frontend (terminal 2) → http://127.0.0.1:5173
bash demo_requests.sh                                          #    optional: scripted API calls instead of the UI
```

### Fraud rules, demo scenarios and AI explanations

Every order gets an **overall risk**. It starts at the AI model's own fraud probability; each matched rule then adds
its weight of the risk that is left (`new = old + (100% − old) × weight`). Decision: a hard rule (known fraud address
or payment method) stops the order; otherwise **≥ 85% stop (fraud)**, **≥ 60% team review**, **≥ 30% verify**, and
below 30% the model and cost policy decide. "Confirmed fraud" = an analyst rejected the order or verification failed
3 times; its device, payment method and address then count as known fraud for later orders. The 8 shipment rules
(`fraudshield/rules.py`) need the optional "Extra signals" on the form (device, payment method and its age, parcel
weight, street address, booking time). Their weights are hand-set expert weights, not learned from DataCo.

The **Fraud demos** buttons (`fraudshield/demo_scenarios.py`) set up one fresh demo customer per scenario: each of the
8 rules alone, and 3 combinations (review by two medium rules, review by a takeover pattern, stop by three rules at
92.8%). The UI shows what was set up, how the risk adds up, and the expected outcome.

**AI explanation** (`fraudshield/genai.py`): OpenRouter writes a plain-language paragraph from a fixed fact pack;
every number in it is checked against the facts, otherwise the standard explanation is shown. Put your key in a
git-ignored `.env` (copy `.env.example`): `OPENROUTER_API_KEY=...`, `OPENROUTER_MODEL=qwen/qwen3.8-27b:free`.

Example buttons on the form fill in orders that reach each outcome: a debit card order is confirmed with a
tracking ID and label; a bank transfer from a returning customer goes to the analyst queue (approve → tracking ID,
reject → blocked); a bulk discounted transfer asks for a one-time code (three wrong codes → blocked). The model
never chooses BLOCK by itself on DataCo (its highest score is about 21%), so blocks come from failed verification
or an analyst rejection. The demo shows the one-time code on screen because there is no SMS gateway.

Each run regenerates the synthetic stream deterministically (seed 7). LightGBM is optional —
the code falls back to scikit-learn's histogram GBM.

## Headline results (synthetic stream, relative numbers)

| | |
|---|---|
| Ranking (all features) | AUC 0.998 · 96 % of fraud caught at 1 % false-positive rate |
| Live replay, cost-sensitive policy | 94.7 % of fraud stopped before shipping · 0.30 % of legitimate bookings blocked · realised cost ₹57.8k vs ₹566.9k for a fixed threshold and ₹126.6k with no detection |
| Latency of the synchronous path | p50 2.2 ms · p99 3.4 ms (in-process) |
| Explanations | grounded and verified; hallucinated narrative rejected |
| Ledger | hash chain verified · tamper detected · decision replay reproduced |

Start with `notes/architecture.md` and `notes/novelty.md`.

## Real data: DataCo Supply Chain (test window 2017-07 → 2018-01, 13,670 orders, 308 fraud)

Reported separately: these are not comparable with the synthetic numbers above.

| | |
|---|---|
| Leaky model (post-booking columns kept, as in most DataCo notebooks) | ROC-AUC 0.990, all from `delivery_status` = 'Shipping canceled' |
| Honest booking-time model | ROC-AUC 0.880 overall. **Inside TRANSFER orders: 0.539 [0.507, 0.572]**, barely above a shuffled-label null of 0.501 ± 0.013 |
| Why | every fraud order is TRANSFER; inside TRANSFER no feature, entity link or anomaly score separates fraud |
| Pipeline replay | ledger verified, tamper detected, replay reproduced. The cost-sensitive policy is cheapest under stated, simulated cost assumptions, because of how it chooses actions rather than better ranking |

Details: `notes/comparison-dataco.md`. Presentation outline and demo steps: `notes/presentation-outline.md`.

