# FraudShield — pipeline architecture

Companion diagram: `visuals/architecture.svg` (`architecture.html` for a browser).
Runnable reference implementation of lanes 3–6 and the three async services:
`prototypes/fraudshield-pipeline/` (`python3 demo.py`, `uvicorn api:app`).

---

## 0. Design principles (the "why" behind every box)

| # | Principle | Consequence in the architecture |
|---|-----------|--------------------------------|
| P1 | **Decide before the parcel moves.** | A synchronous scoring call sits inside the booking transaction with a hard SLA; everything that cannot meet the SLA (LLM narration, analyst review, retraining) is asynchronous. |
| P2 | **The identity is real; the behaviour is not.** | Detection is anchored on *deviation from the shipper's own normal* and on *links to other compromised accounts*, not on identity verification. |
| P3 | **Point-in-time correctness, one feature definition.** | The same feature code replays history offline (training) and runs online (serving); labels enter the store only after their real-world delay. No train/serve skew, no leakage. |
| P4 | **False-positive control is an economic decision.** | The action is chosen by minimising expected cost for *that* booking (loss at stake, customer value, analyst capacity), not by a global probability threshold. |
| P5 | **Every decision is reproducible.** | Feature vector + all version ids + scores + action go into an append-only hash-chained ledger; any decision can be replayed. |
| P6 | **GenAI explains, it never decides.** | The LLM narrates an evidence pack produced by the deterministic pipeline and is checked by a grounding verifier. |
| P7 | **Learn from every touch.** | Step-up outcomes and analyst decisions are labels within hours; post-delivery detection (today's process) remains a label source; unverified bookings never update a shipper's baseline. |

---

## 1. Sources

| Source | What we take | Mode |
|--------|--------------|------|
| Booking API / UI | the booking being created (see contract §4.1), session/device context | synchronous call |
| Account master (MDM) | account age, tier, KYC status, registered addresses, contacts, recent changes (password/e-mail/phone) | CDC stream → `entity.updated` |
| Payment gateway | instrument id (tokenised), age, BIN country, recent add/remove events, AVS/3DS results | event stream |
| Device / session telemetry | device fingerprint hash, IP → geo/ASN, user-agent class, session age | attached to the booking |
| Delivery & case outcomes | undeliverable / returned / charge-back / disputed / confirmed-fraud, analyst decisions | `label.confirmed` (delayed) |

## 2. Ingestion

- **Kafka** (or Redis Streams for the hackathon) topics: `booking.created`, `entity.updated`,
  `label.confirmed`, `decision.made`, `verification.result`. Partition by `shipper_id` so all
  updates to one shipper's profile are ordered. Schema registry (Avro/JSON-schema) so the feature
  code is compiled against a contract.
- **Synchronous scoring endpoint** (`POST /score`, REST/gRPC) called by the booking service.
  SLA p99 < 150 ms end-to-end. Fail-safe modes are *configured by value*: if the scorer is
  unavailable, bookings below a charge threshold are allowed and flagged for post-hoc scoring;
  above it they are held. Idempotent by `booking_id` (retries never double-decide).

## 3. Feature platform

The prototype's `OnlineFeatureStore` (`prototypes/data/featurize.py`) is the executable spec.
Each family maps to an online-store structure:

| Family | Features (prototype names) | Online storage | Cold-start handling |
|--------|---------------------------|----------------|---------------------|
| Behavioural profile | `dest_addr_nov`, `dest_city_nov`, `origin_nov`, `service_nov`, `contents_nov`, `hour_nov`, `w_z`, `val_z` | one Redis hash per shipper: category counters, 24-bin hour histogram, Welford moments of log-weight / log-value | Dirichlet-smoothed categorical probabilities and shrunken Gaussians **back off to the shipper's cohort** (pseudo-counts α = 3, K = 5) |
| Velocity | `vel_1h`, `vel_24h`, `vel_7d`, `vel24_ratio` (vs the shipper's own baseline rate) | sliding-window sorted set per shipper | baseline falls back to the cohort rate until 3 bookings exist |
| Identity & account | `new_device`, `new_payment`, `log_pay_age_min`, `account_age_days`, `days_since_last` | shipper hash (device set, instrument set, first-use times) | first booking ⇒ everything is "new" — the model learns that a brand-new *account* is different from a brand-new *device on an old account* |
| Entity graph | `dest_fanin_30d`, `dev_shared_n`, `pay_shared_n`, `dest_fraud`, `dev_fraud`, `pay_fraud`, `comp_shippers`, `comp_fraud_ratio` | entity → {shipper: last_seen} hashes; degree-capped union-find for connected components; confirmed-fraud counters per entity and per component | — |
| Composite | `drift_score` (unsupervised, label-free) | computed | — |

Rules that keep the store honest:

- **Point-in-time**: features are computed *before* the booking is absorbed; labels are applied
  only when their confirmation time has passed (10 days for post-delivery detection, ~1 day for
  step-up / analyst outcomes).
- **Super-node guard**: an entity used by more than N shippers (addresses 6, devices/instruments
  10) never bridges components — otherwise every fulfilment-centre address glues the graph into
  one giant blob.
- **Burn only what the fraudster brought**: when a booking is confirmed fraudulent, only entities
  the shipper had *not* been using for > 7 days are marked bad. The victim's own card, device and
  regular customers are not poisoned (the account is re-secured instead). Without this, the
  prototype cascaded into blocking 11 % of legitimate traffic.
- **Bounded counters**: cumulative counts are capped so the tree model never sees values it did
  not see in training as months pass (`comp_fraud` drifted 4 → 30 → 108 before capping).
- **Profile quarantine**: a booking that was held/blocked and not verified never updates the
  behavioural profile (otherwise the second booking of a fraud burst looks "seen before").

Offline store: the same class replays warehouse history (Parquet) to build training sets;
training/serving skew is structurally impossible because there is one implementation.

## 4. Contracts

### 4.1 Booking event (input)
```
booking_id, ts, shipper_id, cohort, account_age_days, ltv (customer value proxy),
origin_city, dest_city, dest_address_id, weight_kg, service, contents, declared_value,
charge_inr, payment_id (token), pay_age_min, device_id (hash), hour
```
### 4.2 Decision record (ledger line, `prototypes/fraudshield-pipeline/ledger.jsonl`)
```
booking_id, ts, p_fraud, rules{score, hits[], hard_block, version}, conformal{set, p-values},
decision{action, expected_costs{ALLOW, STEP_UP, HOLD, BLOCK}, reason, policy}, latency_ms,
feature_version, model_version, features{…39 numbers…}, seq, prev_hash, hash
```
### 4.3 Label event
```
booking_id, outcome ∈ {confirmed_fraud, verified_legit, not_shipped, unknown}, source ∈
{step_up, analyst, post_delivery, chargeback}, ts
```

## 5. Detection ensemble (parallel, on the synchronous path)

| Detector | Role | Prototype evidence |
|----------|------|--------------------|
| **Rules engine** (`rules.py`) — versioned, reason-coded, some marked *hard* | analyst-owned knowledge, instant blocks on known-bad infrastructure, safety net if the model is down | rules alone: 76 % recall at 1 % FPR (exp. A) |
| **Supervised GBM** (LightGBM) on all feature families, exact TreeSHAP attributions via `pred_contrib` | the main ranker | AUC 0.998, AP 0.975, 96 % recall at 1 % FPR (exp. A); behavioural features only: 87 % |
| **Behavioural drift** (unsupervised composite of the profile deviations) | label-free detector; fed to the GBM as a feature; standalone fallback | AUC 0.968 standalone; cohort back-off lifts cold-start AUC 0.82 → 0.95 (exp. C) |
| **Entity-graph signals** | rings and mules; label propagation from confirmed cases | graph-only 92 % recall at 1 % FPR; 83 % of live-period fraud touches already-confirmed infrastructure (exp. B) |

Fusion happens **at feature level** (one model sees everything) rather than by averaging four
scores: the GBM learns the interactions (e.g. "new device × first-time destination × destination
shared by 3 other accounts") that separate the stealthy scenario. Rules are combined by noisy-OR
and can force BLOCK.

**Calibration**: Platt scaling on a time-ordered hold-out slice, because the decision engine
consumes *probabilities*. (Isotonic regression collapsed into 0/1 plateaus with ~40 calibration
fraud cases and broke the threshold policies — a real finding worth mentioning to judges.)

**Uncertainty**: Mondrian (class-conditional) split-conformal prediction gives every decision a
prediction set at 90 % confidence: `{legit}`, `{fraud}` or `{legit, fraud}`. The ambiguous set is
the trigger for spending analyst capacity.

## 6. Decision engine (`decision.py`)

Actions: **ALLOW · STEP_UP (verify with the account owner) · HOLD (analyst review before pickup)
· BLOCK**. For each booking compute, in rupees,

```
L        = charge × (1 + ops_factor)                loss if fraud is allowed
C_block  = charge + churn_if_blocked × LTV         cost of blocking a legitimate customer
C_stepup = stepup_friction × LTV + abandon × charge
C_hold   = analyst_cost + hold_delay × LTV

E[ALLOW]   = p·L
E[BLOCK]   = (1−p)·C_block
E[STEP_UP] = p·q_fraud_pass·L + (1−p)·[C_stepup + (1−q_legit_pass)·C_block]
E[HOLD]    = analyst_cost + (1−p)·delay + p·(1−catch)·L        (only if capacity and conformal-ambiguous)
action     = argmin, unless a hard rule fired (→ BLOCK)
```

Consequences that a threshold cannot express (measured, `prototypes/fraudshield-pipeline/results.md`):

- a ₹300 parcel at p = 0.6 → STEP_UP for an individual, STEP_UP for an SME, **ALLOW** for an
  e-commerce account worth ₹3 lakh/yr (the friction costs more than the parcel);
- a ₹3,000 parcel at p = 0.3 → HOLD for everyone (the loss justifies an analyst);
- on the replay, the cost-sensitive policy realised ₹57.8k of total cost vs ₹566.9k for a fixed
  1 %-FPR threshold and ₹349.8k for a two-threshold review band — because it blocked 19 legitimate
  bookings instead of 74, while still stopping 107/113 fraud attempts (vs 110/113).

The cost parameters are **business-owned configuration**, versioned like rules; the engine is
transparent about them (every ledger record carries the four expected costs).

## 7. Actions & integration

| Action | Integration | Label produced |
|--------|-------------|----------------|
| ALLOW | booking proceeds; decision id attached | post-delivery outcome (days) |
| STEP_UP | verification workflow: OTP to registered phone/e-mail, call-back, or prepayment; booking auto-cancels if unverified in T minutes | pass ⇒ `verified_legit`, fail/timeout ⇒ `confirmed_fraud` (hours) |
| HOLD | case created in the analyst queue, prioritised by expected loss; ops instructed to hold at pickup / first scan | analyst decision (hours) |
| BLOCK | booking rejected with a reference; customer-facing message never reveals features; support can verify and release | support outcome |

## 8. GenAI explanation service (asynchronous)

1. **Evidence pack** (deterministic): top-k SHAP attributions with human labels and displays,
   rule hits with text, graph facts, drift facts, conformal set, and **counterfactuals** (the
   single feature change to the shipper's typical value that would clear the threshold).
2. **Narratives**: an analyst narrative and a customer message rendered from the *same* pack by an
   LLM (prompt contract in `explain.py::llm_prompt`) or by the deterministic template.
3. **Grounding verifier**: every number and identifier in the narrative must occur in the pack;
   otherwise the narrative is rejected and regenerated / replaced by the template. (Exp. D: 7/7
   generated narratives pass; a deliberately hallucinated one is rejected with the offending
   tokens named.)
4. Cached per decision id, written to the case and to the ledger.

## 9. Auditability & compliance

- **Hash-chained ledger** (`ledger.py`): each record includes `prev_hash`; `verify()` walks the
  chain; `replay(booking_id, model)` re-scores the stored feature vector with the stored model
  version and confirms the probability is reproduced. The demo shows a one-character tamper being
  detected at the exact record.
- **Versions everywhere**: `feature_version`, `model_version` (content hash), `rules.version`,
  `decision.policy`. Model registry (MLflow) holds artefacts + training-set lineage.
- **PII minimisation**: the scorer sees tokens/hashes (instrument token, device hash, address id),
  never raw card numbers or free-text addresses; retention and access are per-record.
- **Analyst overrides** are ledger events too, so precision/recall of the humans is measurable.

## 10. Feedback & learning

| Loop | Latency | Mechanism |
|------|---------|-----------|
| Step-up outcomes | minutes–hours | `verification.result` → label; failed step-up burns the fraudster's entities immediately |
| Analyst decisions | hours | case close → label; overrides tracked |
| Post-delivery detection (today's process) | days | `label.confirmed` → entity-graph propagation, training labels |
| Profile hygiene | immediate | quarantine of unverified bookings; re-securing a compromised account resets nothing of the victim's own history |
| Model refresh | weekly (or on drift) | scheduled retrain on the replayed offline store; PSI / score-drift monitors on features and outputs |
| Policy/model rollout | continuous | **champion/challenger shadow scoring** (the demo evaluates two challenger policies in shadow on the same probabilities) |
| Rule mining | weekly | frequent-pattern mining over confirmed cases → proposed rules with measured precision, for analyst sign-off |

## 11. Non-functional design

- **Latency budget** (target p99 150 ms): network + auth 20 · feature fetch (3 Redis round-trips,
  pipelined) 15 · rules + GBM + conformal + policy 10 · ledger write (async ack) 5 · headroom.
  The prototype measures **p50 2.2 ms, p99 3.4 ms** for the in-process part.
- **Throughput**: stateless scorers behind a load balancer; Redis cluster keyed by `shipper_id`;
  union-find lives in a graph service (or Redis Graph / a small Neo4j) updated by a consumer.
- **Degraded modes**: model unavailable ⇒ rules + drift score only (still decides); feature store
  unavailable ⇒ value-based fail-safe; LLM unavailable ⇒ template narrative.
- **Security**: mTLS between services, scoped tokens, audit of who read which case.

## 12. Hackathon-feasible stack

| Layer | Hackathon | Production |
|-------|-----------|------------|
| Ingestion | Redis Streams or a Python queue; `api.py` (FastAPI) | Kafka + schema registry, gRPC |
| Feature store | `OnlineFeatureStore` in-process (dicts) → Redis with the same keys | Feast on Redis + warehouse |
| Models | LightGBM, scikit-learn, the composite drift score | same, in a model registry |
| Graph | dict-of-sets + union-find | graph service / Neo4j for analyst exploration |
| Decision | `decision.py` | same, policy in config service |
| Explanation | template + optional LLM API | LLM behind the verifier, cached |
| Ledger | JSONL hash chain | append-only table / object store with WORM retention |
| Dashboard | static HTML (`visuals/dashboard.html`) or Streamlit | Grafana / Superset |
| Data | `simulate.py` scenario generator | carrier history |

## 13. Build plan (48 h, four people)

| Track | Hours 0–8 | 8–24 | 24–40 | 40–48 |
|-------|-----------|------|-------|-------|
| Data & features | adopt/extend the simulator (add real-looking address text, more scenarios) | feature store on Redis | drift monitors | freeze |
| Detection | retrain GBM, tune rules | graph service, mule ranking | conformal, calibration checks | freeze |
| Decision & integration | FastAPI `/score`, `/feedback` | step-up workflow stub (OTP mock), analyst queue UI | champion/challenger | rehearse |
| Explanation & UI | evidence pack + verifier | LLM prompt + customer message | dashboard, ring graph view | pitch |

Demo storyline (10 minutes): normal booking → ALLOW in ms → an ATO booking → BLOCK with a grounded
explanation and counterfactual → the same p on an e-commerce account → STEP_UP, show expected
costs → the ring graph lighting up as confirmed labels arrive → the policy comparison bars → tamper
the ledger live and show the chain break → the replay reproducing a decision.

## 14. What the prototype measures (synthetic stream — relative numbers)

| Metric | Value | Where |
|--------|-------|-------|
| Ranking, all features | AUC 0.998 · AP 0.975 · 96 % recall at 1 % FPR | `experiments/a-rules-gbm-shap/results.md` |
| Graph-only recall at 1 % FPR | 92 % | `experiments/b-entity-graph/results.md` |
| Unsupervised drift, cold-start AUC with/without cohort back-off | 0.95 / 0.82 | `experiments/c-behavioral-drift/results.md` |
| Grounding verifier | 7/7 narratives pass; hallucinated narrative rejected | `experiments/d-grounded-explanation/results.md` |
| Live replay: fraud stopped · legit blocked · realised cost | 94.7 % · 0.30 % · ₹57.8k (vs ₹566.9k fixed threshold, ₹126.6k no detection) | `prototypes/fraudshield-pipeline/results.md` |
| Latency (in-process) | p50 2.2 ms · p99 3.4 ms | same |
| Ledger | chain valid · tamper detected · replay reproduced | same |
