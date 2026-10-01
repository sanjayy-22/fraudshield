# Novelty — what to build to stand out, and how to pitch it

Judges at a problem-statement hackathon score four things: does it work end-to-end, is it
technically credible, is there something the other teams did not think of, and can the team
defend it under questioning. Most teams will bring *a classifier + an LLM that explains the
classifier*. The list below is ordered by (novelty × demo-ability × defensibility).

## 1. Cost-sensitive step-up decisioning (the "false-positive control" made measurable)

**What**: choose ALLOW / STEP_UP / HOLD / BLOCK by minimising expected cost per booking
(`decision.py`), with customer value, loss at stake, verification pass-rates and analyst capacity
as inputs; conformal ambiguity gates the analyst budget.

**Why it wins**: the problem statement lists "false positive control" and "action framework" as
separate bullets; everyone else will implement them as two thresholds. You show the same
probability producing different actions for different customers, and a replay where the fixed
threshold that "catches 97 %" costs 10× more than your policy once churn is priced in.

**Demo**: the sensitivity table (`results.md`), the policy-cost bars on the dashboard, and a live
`/score` call where you change `ltv` in the JSON and the action flips.

**Likely question**: "Where do the cost parameters come from?" — Answer: they are business-owned
configuration, versioned like rules, and the ledger stores the four expected costs of every
decision so finance can audit the trade-off. Sensitivity to them is a one-line experiment.

## 2. Streaming entity graph with rotation-proof mule discovery

**What**: shippers ↔ addresses ↔ devices ↔ payment instruments as O(1) hash-map counters plus a
degree-capped union-find; confirmed labels propagate along shared infrastructure; an unsupervised
"novelty-mass" score finds mule addresses even before labels arrive.

**Why it wins**: ATO fraud is organised. The graph is what catches the *stealthy* scenario that
copies the victim's own behaviour (behavioural features alone: 87 % recall; with graph: 96 %).
The super-node guard and "first-time-for-that-shipper" weighting show you understood that
fulfilment hubs also have high fan-in — a trap most teams fall into.

**Demo**: `visuals/ring_graph.png`; the mule ranking table (naive fan-in precision@10 = 0.5 →
novelty-mass 1.0); a booking to a fresh address that is nevertheless blocked because the device
was seen on another account's confirmed fraud.

## 3. Per-shipper behavioural fingerprint with cohort back-off

**What**: Bayesian running profile per shipper (Dirichlet-smoothed categoricals, shrunken
Gaussians, own-baseline velocity) that backs off to the cohort when history is thin.

**Why it wins**: it answers "how do you handle new or dormant accounts?" with a number (cold-start
AUC 0.82 → 0.95) and it is the label-free detector that keeps working when tactics change. It
also produces the most business-readable explanation there is: "this shipper has never sent
more than 6 kg; this booking is 22 kg, +4.1 σ".

## 4. Grounded GenAI with a hallucination verifier and counterfactuals

**What**: the LLM sees only an evidence pack; a regex-level verifier rejects any narrative that
cites a number or identifier not in the pack; counterfactuals tell the analyst what to verify.
Two narratives per decision (analyst / customer), the customer one never revealing features.

**Why it wins**: "GenAI-powered anomaly explanation" is in the brief, so every team has it. Yours
is *admissible in an audit* because it cannot invent facts, and it is actionable because it says
what would make the booking normal. Show the rejected hallucination live.

## 5. Hash-chained decision ledger with deterministic replay

**What**: every decision → feature vector + all versions + scores + action + expected costs, hash
chained; `verify()` and `replay()`.

**Why it wins**: "auditability & compliance" is usually a slide. Yours is a 60-line module and a
live demonstration: edit one character in the log, the chain breaks at that record; replay a
decision from last week and get the same probability.

## 6. Fraud-scenario simulator as an adversarial test bench

**What**: `simulate.py` generates a population of shippers, six ATO scenarios, rings that rotate
their infrastructure, legitimate look-alikes (sale-day bursts, new cards, new devices, hubs).

**Why it wins**: nobody has real data. Teams that train on a Kaggle credit-card set are answering
a different question. A scenario generator lets you say "here is the attack we did not catch"
(stealthy mule: 69 % in the live replay), which is more credible than a 100 % slide. It also
doubles as a red-team loop: add a scenario, see what breaks.

## 7. Feedback hygiene most teams miss (small, but judges who know fraud will notice)

- **Profile quarantine**: unverified bookings never teach the baseline that the mule address is
  normal.
- **Burn only what the fraudster brought**: confirmed fraud marks the fraudster's device/card/
  address, not the victim's — the prototype cascaded into blocking 11 % of legitimate traffic
  before this fix, which is a good story about why feedback loops need care.
- **Step-up outcomes as labels within hours**, not days.
- **Bounded counters** so the tree model does not drift as months of cumulative counts pile up.

## What NOT to lead with

- A GNN. It is slower to serve, harder to explain, and on this problem a degree-capped graph
  counter feeds the same signal to a GBM in microseconds. Mention it as future work.
- LLM-as-the-detector. Non-deterministic, slow, expensive, unauditable on the synchronous path.
  Keep it as a tier-2 idea (see `next-experiments.md`).
- Absolute accuracy numbers. Say "on our simulator" every time; judges trust relative claims.

## One-sentence pitch

*"FraudShield decides at booking time — in milliseconds — whether to allow, verify, review or
block, by comparing the booking with the shipper's own history and with a live graph of
compromised infrastructure, choosing the action that costs the carrier least, and writing an
explainable, tamper-evident record of why."*
