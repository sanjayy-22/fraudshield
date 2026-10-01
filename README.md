# FraudShield — early detection of fraudulent shipping bookings

Booking-time fraud screening for a parcel carrier: decide **ALLOW / STEP-UP / HOLD / BLOCK** in
milliseconds, explain it in plain language, and record it in a tamper-evident ledger.

```
notes/         framing, target architecture, novelty pitch, comparison, next experiments
visuals/       architecture diagram (svg/html), ring graph, replay dashboard
prototypes/
  data/        simulate.py   synthetic booking stream with ATO fraud rings (no real data needed)
               featurize.py  point-in-time online feature store (behaviour, velocity, identity, graph)
  fraudshield-pipeline/      end-to-end prototype: rules ⊕ calibrated GBM ⊕ drift ⊕ graph
                             → conformal set → cost-sensitive decision → audit ledger → explanation
                             demo.py (replay + policy comparison + dashboard), api.py (FastAPI)
experiments/
  a-rules-gbm-shap/          supervised tabular detector + attributions
  b-entity-graph/            ring / mule detection, feature-group ablation, ring picture
  c-behavioral-drift/        unsupervised per-shipper fingerprint, cold start
  d-grounded-explanation/    evidence pack → narrative → hallucination verifier → counterfactuals
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
cd prototypes/fraudshield-pipeline && uvicorn api:app --port 8080   # POST /score, GET /explain/{id}, POST /feedback
```

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
