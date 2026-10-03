"""FraudShield on real data: replay the DataCo test window (2017-07 → 2018-01) order by order.

The same components as demo.py (calibrated GBM → Mondrian conformal → cost-sensitive decision →
hash-chained ledger → replay check) are reused unchanged. The changes are only the ones the
data forces:
* features come from prototypes/data/dataco_features.py (the booking-time contract, no leaks);
* categoricals are integer-coded with codes frozen from the training split, because RiskModel
  takes a plain float matrix and the ledger must replay an order from its stored vector;
* money is USD (DataCo `order_item_total`). LTV is not in the data, so it is approximated as
  max(2 × prior spend, order value). analyst_cost is 5 USD. These are assumptions, stated in results_dataco.md.

Policies compared on identical probabilities and outcomes:
    allow all · rule: step-up every TRANSFER · fixed threshold @1% FPR · two-threshold band ·
    cost-sensitive + conformal (live)

Outputs: results_dataco.md, ledger_dataco.jsonl (git-ignored, ~20 MB).
"""
from __future__ import annotations

import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "prototypes" / "data"))
import dataco_features as F                                                     # noqa: E402
import dataco_protocol as P                                                     # noqa: E402
from fraudshield.conformal import MondrianConformal                             # noqa: E402
from fraudshield.decision import (CostParams, ReviewCapacity, banded, cost_sensitive,  # noqa: E402
                                  fixed_threshold, realized_cost, unit_costs, Decision)
from fraudshield.ledger import AuditLedger                                      # noqa: E402
from fraudshield.model import RiskModel                                         # noqa: E402
from fraudshield.rules import Rule, RuleResult                                  # noqa: E402

FEATURE_VERSION = "dataco-features-2026.10.1"
COLS = F.honest_features(include_payment=True)
CP = CostParams(analyst_cost=5.0)          # USD; every other parameter is a share of charge / LTV

# Informational rules for DataCo. None is hard: the E3 audit found prior fraud on the customer does not
# raise the next order's fraud rate (0.075 vs 0.083), so a hard block would only add false positives.
DATACO_RULES = [
    Rule("D01_TRANSFER", 0.08, "bank-transfer payment (the only payment type with fraud in DataCo)",
         lambda f: f["is_transfer"] == 1),
    Rule("D02_PRIOR_FRAUD_CUSTOMER", 0.08, "customer had an earlier order flagged SUSPECTED_FRAUD",
         lambda f: f["cust_prior_fraud"] >= 1),
    Rule("D03_HIGH_DISCOUNT_NEW_CUSTOMER", 0.05, "first order with discount rate ≥ 20 %",
         lambda f: f["cust_n_prior"] == 0 and f["discount_rate_max"] >= 0.2),
]


def evaluate_rules(f: dict) -> RuleResult:
    hits = [r for r in DATACO_RULES if r.predicate(f)]
    score = 1.0 - float(np.prod([1 - r.weight for r in hits])) if hits else 0.0
    return RuleResult(score=score, hits=[r.code for r in hits], hard_block=False, version="dataco-rules-2026.10.1")


class CategoryCoder:
    """Freeze category → integer codes on the training split (unseen values → -1)."""

    def __init__(self, train: pd.DataFrame):
        self.maps = {c: {v: i for i, v in enumerate(sorted(train[c].astype(str).unique()))} for c in F.CAT_COLS}

    def transform(self, d: pd.DataFrame) -> pd.DataFrame:
        X = d[COLS].copy()
        for c in F.CAT_COLS:
            X[c] = X[c].astype(str).map(self.maps[c]).fillna(-1).astype(float)
        return X.astype(float)


def main():
    o = F.cached_orders()
    F.assert_no_leak(COLS)
    tr, va, te = F.split(o)
    coder = CategoryCoder(tr)
    Xtr, Xva, Xte = coder.transform(tr), coder.transform(va), coder.transform(te)

    # train / calibrate / conformal, all strictly before the test window
    half = va.ts.quantile(0.5)
    va_a, va_b = va.ts < half, va.ts >= half
    model = RiskModel(COLS).fit(Xtr, tr.is_fraud.values)
    model.calibrate(Xva[va_a.values], va.is_fraud.values[va_a.values])
    p_b = model.predict_proba(Xva[va_b.values]); y_b = va.is_fraud.values[va_b.values]
    conformal = MondrianConformal().fit(p_b, y_b)
    neg = np.sort(p_b[y_b == 0])[::-1]
    thr = {k: float(neg[min(int(q * len(neg)), len(neg) - 1)]) for k, q in [("0.5", 0.005), ("1", 0.01), ("2", 0.02)]}

    ledger_path = HERE / "ledger_dataco.jsonl"
    if ledger_path.exists():
        ledger_path.unlink()
    ledger = AuditLedger(ledger_path)

    policies = ["allow all", "rule: step-up every TRANSFER", "fixed threshold @1% FPR",
                "two-threshold + review band", "cost-sensitive + conformal (live)"]
    caps = {"two-threshold + review band": ReviewCapacity(2, 4), "cost-sensitive + conformal (live)": ReviewCapacity(2, 4)}
    cost = Counter(); outcomes = {p: Counter() for p in policies}; actions = {p: Counter() for p in policies}
    rng = np.random.default_rng(7)
    fraud_at_risk, probs, ambiguous = 0.0, [], 0
    records = te.to_dict("records")
    X_rows = Xte.to_dict("records")

    for b, f in zip(records, X_rows):
        charge = float(b["net_total"])
        ltv = max(2.0 * float(b["cust_prior_spend"]), charge)
        ts = pd.Timestamp(b["ts"])
        y = bool(b["is_fraud"])
        p = model.predict_one(f)
        probs.append(p)
        rr = evaluate_rules(f)
        conf = conformal.prediction_set(p, 0.10)
        ambiguous += int(conf["ambiguous"])
        live = cost_sensitive(p, charge, ltv, CP, caps[policies[4]], ts, rr.hard_block, conf)
        decisions = {
            policies[0]: "ALLOW",
            policies[1]: "STEP_UP" if f["is_transfer"] == 1 else "ALLOW",
            policies[2]: fixed_threshold(p, thr["1"]).action,
            policies[3]: banded(p, thr["2"], thr["0.5"], caps[policies[3]], ts).action,
            policies[4]: live.action,
        }
        if y:
            fraud_at_risk += unit_costs(charge, ltv, CP)["L"]
        for pol, act in decisions.items():
            c, out = realized_cost(act, y, charge, ltv, CP, rng)
            cost[pol] += c; outcomes[pol][out] += 1; actions[pol][act] += 1
        ledger.append(dict(
            booking_id=f"dataco-{b['order_id']}", customer_id=int(b["customer_id"]), ts=str(ts),
            charge_usd=round(charge, 2), ltv_usd=round(ltv, 2), p_fraud=p, rules=dict(score=rr.score, hits=rr.hits),
            conformal=conf, decision=dict(action=live.action, expected_costs=live.expected_costs, reason=live.reason,
                                          policy=live.policy),
            feature_version=FEATURE_VERSION, model_version=model.version, features=f))

    # ------------------------------------------------------------------ summaries
    y_te = te.is_fraud.values
    ev = P.evaluate(te, np.array(probs))
    n_fraud, n_legit = int(y_te.sum()), int((y_te == 0).sum())
    lines = ["| policy | realised cost (USD) | fraud stopped | legit blocked | legit asked to verify | reviews | ALLOW/STEP_UP/HOLD/BLOCK |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for pol in policies:
        oc = outcomes[pol]
        lines.append(f"| {pol} | {cost[pol]:,.0f} | {oc['fraud_stopped']}/{n_fraud} ({oc['fraud_stopped']/n_fraud:.1%}) | "
                     f"{oc['legit_blocked'] + oc['legit_failed_stepup']} ({(oc['legit_blocked'] + oc['legit_failed_stepup'])/n_legit:.2%}) | "
                     f"{oc['legit_verified'] + oc['legit_failed_stepup']} | {actions[pol]['HOLD']} | "
                     + "/".join(str(actions[pol][a]) for a in ("ALLOW", "STEP_UP", "HOLD", "BLOCK")) + " |")

    import json
    (HERE / "stats_dataco.json").write_text(json.dumps(dict(
        policies={pol: dict(cost_usd=round(cost[pol], 2), fraud_stopped=outcomes[pol]["fraud_stopped"],
                            legit_blocked=outcomes[pol]["legit_blocked"] + outcomes[pol]["legit_failed_stepup"],
                            actions=dict(actions[pol])) for pol in policies},
        fraud_at_risk_usd=round(fraud_at_risk, 2), n_fraud=n_fraud, n_legit=n_legit), indent=1), encoding="utf-8")

    ok, n_rec = ledger.verify()
    first = next(ledger.records())
    replay = ledger.replay(first["booking_id"], model)
    tampered = ledger_path.read_text(encoding="utf-8").splitlines()
    tampered[5] = tampered[5].replace('"action":"', '"action":"X', 1)
    tmp = HERE / "ledger_dataco_tampered.jsonl"
    tmp.write_text("\n".join(tampered) + "\n", encoding="utf-8")
    ok_t, n_t = AuditLedger(tmp).verify()
    tmp.unlink()

    # explanation sample: the highest-scored fraud and the highest-scored legitimate order
    probs_a = np.array(probs)
    def top_reasons(i):
        c = model.contributions(X_rows[i]).sort_values(ascending=False).head(4)
        return ", ".join(f"`{k}`={X_rows[i][k]:.3g} (+{v:.2f})" for k, v in c.items())
    i_f = int(np.argmax(np.where(y_te == 1, probs_a, -1))); i_l = int(np.argmax(np.where(y_te == 0, probs_a, -1)))

    P.write(HERE / "results_dataco.md", f"""
# FraudShield replay on real data: DataCo, 2017-07 → 2018-01

Training: {len(tr)} orders (2015–2016). Calibration and conformal fit: 2017-H1, split in half.
Replay: {len(te)} orders ({n_fraud} fraud), in time order, through the live path. Model `{model.version}`,
features `{FEATURE_VERSION}` ({len(COLS)} booking-time features, `assert_no_leak` passed).

## Ranking quality of the calibrated live model
{P.metrics_table({"live RiskModel (calibrated)": ev})}

## Policy comparison: same probabilities, same simulated outcomes
Fraud value at risk if everything is allowed: **{fraud_at_risk:,.0f} USD**.

{chr(10).join(lines)}

Conformal sets (α = 0.10) were ambiguous for {ambiguous} of {len(te)} orders ({ambiguous/len(te):.1%}). Only these
are eligible for analyst review under the live policy.

### Reading
- On this data every policy can only work on one fact: whether the order is TRANSFER. Inside TRANSFER
  the model's ranking is barely better than chance (see E2/E5), so the policies differ mainly in
  *what they do* with TRANSFER orders (allow, verify, review or block), not in *which* TRANSFER orders they pick.
- The costs depend on the stated assumptions (USD charge, LTV = max(2 × prior spend, order),
  analyst 5 USD, step-up pass rates from `CostParams`). Re-run with other values before quoting them.

## Explanations (top TreeSHAP log-odds contributions)
- Highest-scored **fraud** order (p = {probs_a[i_f]:.3f}): {top_reasons(i_f)}
- Highest-scored **legitimate** order (p = {probs_a[i_l]:.3f}): {top_reasons(i_l)}

## Audit ledger
- Records: {n_rec}; hash chain verified: **{ok}**
- Tampering with record 5: verification **{'fails' if not ok_t else 'passes (BUG)'}** at record {n_t}
- Replay of `{first['booking_id']}` from its stored feature vector: reproduced = **{replay['reproduced']}**
""")


if __name__ == "__main__":
    main()
