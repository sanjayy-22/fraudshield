# 00 · Framing — FraudShield: early detection of fraudulent shipping bookings

## The problem, restated in one paragraph

Fraudsters book shipments **using the identity, account or payment credentials of a
legitimate shipper** (account takeover, ATO). Today the carrier notices only *after*
delivery, from shipping-pattern analysis. The carrier then absorbs the shipping revenue
(it refunds / does not charge the legitimate shipper to protect goodwill) **and** has
already paid the operational cost of moving the parcel. The ask: a decision at
**booking time** — before the parcel enters the network — that is fast, accurate,
explainable, auditable, and does not punish legitimate customers.

Three things make this harder than "train a classifier":

1. **The identity is real.** KYC-style checks pass; the signal is *behavioural deviation
   from the shipper's own normal* and *links to other compromised accounts*, not a bad
   identity.
2. **Labels arrive late and are sparse.** Confirmed fraud shows up ~days after delivery.
   Anything that needs labels at booking time must be point-in-time correct (no leakage)
   and must degrade gracefully for shippers with little history (cold start).
3. **The cost of a wrong decision is asymmetric and heterogeneous.** Blocking a small
   individual shipper costs almost nothing; blocking an e-commerce account that ships
   2,000 parcels a month is a churn event worth far more than one fraudulent parcel.
   A fixed probability threshold cannot express that.

## Angles of attack considered

| # | Angle | Paradigm | Why it might win | Risk |
|---|-------|----------|------------------|------|
| A | **Rules + gradient-boosted classifier + SHAP** | Supervised tabular ML on point-in-time behavioural features | Strongest single detector when labels exist; SHAP gives per-decision feature attributions that feed the explainer | Needs labels; can only learn fraud patterns already seen |
| B | **Entity graph / ring detection** | Streaming graph over accounts ↔ destination addresses ↔ payment instruments ↔ devices, with delayed label propagation | ATO fraud is organised: mule addresses, drop devices and payment instruments are *reused across victims*. Catches "stealthy" fraud that mimics the victim's normal behaviour | Popular legitimate hubs (fulfilment centres) also have high fan-in; needs a super-node guard |
| C | **Per-shipper behavioural fingerprint with cohort back-off** | Unsupervised Bayesian profile (Dirichlet-smoothed categorical distributions, shrunken Gaussian for weight/value, decayed velocity) | Needs no labels; explains "vs *this* shipper's own normal"; cohort prior handles cold start | Weaker alone; hand-set weights |
| D | **Grounded GenAI explanation layer** | LLM narrates an *evidence pack* (SHAP + rule hits + graph facts + drift stats + counterfactual); a verifier rejects any number or entity not in the evidence | Business-friendly explanations *without hallucination*; dual narratives (analyst / customer) | Latency and cost → must be asynchronous, off the decision path |
| E | **Cost-sensitive step-up decisioning** (unconventional) | Choose ALLOW / STEP-UP-VERIFY / HOLD / BLOCK by minimising expected cost given p, shipment charge, customer value, analyst capacity, and conformal uncertainty | Turns "false-positive control" from a slogan into an optimisation; measurable as rupees | Needs cost parameters the business must own |
| F | **LLM-as-judge with retrieval over shipper history** (high risk) | RAG: retrieve the shipper's last N bookings + current booking → LLM outputs structured risk | Zero feature engineering; handles free-text (contents, addresses) | Too slow/expensive for the synchronous path; non-deterministic; hard to audit — kept as a tier-2 idea only |

Decision for the prototypes: implement **A, B, C, D** as separate experiments on the
same simulated stream, then combine A+B+C as an ensemble and add **E** in the
end-to-end pipeline. **F** is recorded in `notes/next-experiments.md`.

## What "novelty" means for judging

Most teams will show *a classifier + a chatbot that explains it*. The differentiators
that are both real and demoable are:

- an **entity-graph** that catches rings the classifier misses (show the ring picture);
- a **decision engine that optimises cost** instead of thresholding probability, and a
  measurable friction/loss trade-off against fixed thresholds;
- **grounded** explanations with a verifier and **counterfactuals** ("this booking would
  score normal if…");
- a **hash-chained audit ledger** with deterministic replay;
- a **fraud-scenario simulator** used as an adversarial test-bench (because no real
  data is available, and because judges will ask "how do you know it works?").

## Data reality

No carrier data is available, so `prototypes/data/simulate.py` generates a
time-ordered booking stream with injected ATO episodes organised in rings. All metrics
in this repository measure *the simulator*; they are meaningful for **relative**
comparison of approaches, not as production performance claims.
