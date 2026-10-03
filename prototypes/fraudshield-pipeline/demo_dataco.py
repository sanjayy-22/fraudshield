"""FraudShield on real data: replay the DataCo test window (2017-07 → 2018-01) order by order.

The live path is `fraudshield.dataco.DataCoShield`: the same calibrated GBM → Mondrian conformal →
cost-sensitive decision → hash-chained ledger as demo.py, on the leak-free booking-time features
of prototypes/data/dataco_features.py. Assumptions (USD money, LTV, analyst cost) are documented
in fraudshield/dataco.py and repeated in results_dataco.md.

Policies compared on identical probabilities and outcomes:
    allow all · rule: step-up every TRANSFER · fixed threshold @1% FPR · two-threshold band ·
    cost-sensitive + conformal (live)

Outputs: results_dataco.md, stats_dataco.json, ../../visuals/dashboard_dataco.html,
ledger_dataco.jsonl (git-ignored, ~20 MB).
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "prototypes" / "data"))
import dataco_features as F                                                     # noqa: E402
import dataco_protocol as P                                                     # noqa: E402
from fraudshield.dataco import COLS, FEATURE_VERSION, DataCoShield, charge_and_ltv  # noqa: E402
from fraudshield.decision import (ReviewCapacity, banded, fixed_threshold,       # noqa: E402
                                  realized_cost, unit_costs)
from fraudshield.ledger import AuditLedger                                      # noqa: E402
from dashboard_dataco import render_dashboard_dataco                            # noqa: E402

POLICIES = ["allow all", "rule: step-up every TRANSFER", "fixed threshold @1% FPR",
            "two-threshold + review band", "cost-sensitive + conformal (live)"]
LIVE = POLICIES[4]


def experiment_headlines() -> dict:
    """TRANSFER-scope and all-orders AUCs from experiments e0–e5 (if they have been run)."""
    exp = ROOT / "experiments"
    picks = [("e0-dataco-leaky-baseline", "leaky: honest + post-booking columns", "leaky model (post-booking columns)"),
             ("e1-dataco-rule-only", "rule: payment_type == TRANSFER", "rule: flag TRANSFER"),
             ("e2-dataco-honest-gbm", "honest GBM (with payment_type)", "honest GBM"),
             ("e2-dataco-honest-gbm", "honest GBM (no payment_type)", "honest GBM, no payment_type"),
             ("e3-dataco-entity-graph", "GBM + entity counters (with payment_type)", "GBM + entity graph"),
             ("e4-dataco-anomaly", "IsolationForest × TRANSFER gate", "IsolationForest"),
             ("e4-dataco-anomaly", "customer drift × TRANSFER gate", "customer drift")]
    out = []
    for folder, key, label in picks:
        f = exp / folder / "scores.json"
        if f.exists():
            m = json.loads(f.read_text(encoding="utf-8"))["metrics"][key]
            out.append(dict(label=label, leaky=folder.startswith("e0"), all_auc=m["all"]["roc_auc"],
                            transfer_auc=m["transfer"]["roc_auc"], transfer_ci=m["transfer"]["roc_ci"]))
    null_f = exp / "e5-dataco-label-shuffle" / "scores.json"
    null = json.loads(null_f.read_text(encoding="utf-8")) if null_f.exists() else None
    return dict(models=out, null=None if null is None else dict(
        mean=float(np.mean(null["null"])), sd=float(np.std(null["null"])), lo=min(null["null"]),
        hi=max(null["null"]), real=null["real_auc"], p_value=null["p_value"]))


def main():
    o = F.cached_orders()
    tr, va, te = F.split(o)
    ledger_path = HERE / "ledger_dataco.jsonl"
    if ledger_path.exists():
        ledger_path.unlink()
    shield = DataCoShield(ledger_path=ledger_path).fit(o)
    thr, cp = shield.thresholds, shield.cp
    Xte = shield.coder.transform(te)

    band_cap = ReviewCapacity(2, 4)
    cost = Counter(); outcomes = {p: Counter() for p in POLICIES}; actions = {p: Counter() for p in POLICIES}
    rng = np.random.default_rng(7)
    fraud_at_risk, probs, ambiguous, live_actions = 0.0, [], 0, []
    records, X_rows = te.to_dict("records"), Xte.to_dict("records")

    for b, f in zip(records, X_rows):
        r = shield.score(b, f)
        p, act_live = r["p_fraud"], r["decision"]["action"]
        charge, ltv = charge_and_ltv(b)
        ts, y = pd.Timestamp(b["ts"]), bool(b["is_fraud"])
        probs.append(p); live_actions.append(act_live)
        ambiguous += int(r["conformal"]["ambiguous"])
        decisions = {
            POLICIES[0]: "ALLOW",
            POLICIES[1]: "STEP_UP" if f["is_transfer"] == 1 else "ALLOW",
            POLICIES[2]: fixed_threshold(p, thr["fpr_1pct"]).action,
            POLICIES[3]: banded(p, thr["fpr_2pct"], thr["fpr_0_5pct"], band_cap, ts).action,
            POLICIES[4]: act_live,
        }
        if y:
            fraud_at_risk += unit_costs(charge, ltv, cp)["L"]
        for pol, act in decisions.items():
            c, out = realized_cost(act, y, charge, ltv, cp, rng)
            cost[pol] += c; outcomes[pol][out] += 1; actions[pol][act] += 1

    # ------------------------------------------------------------------ summaries
    y_te = te.is_fraud.values
    probs_a = np.array(probs)
    ev = P.evaluate(te, probs_a)
    n_fraud, n_legit = int(y_te.sum()), int((y_te == 0).sum())
    lines = ["| policy | realised cost (USD) | fraud stopped | legit blocked | legit asked to verify | reviews | ALLOW/STEP_UP/HOLD/BLOCK |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for pol in POLICIES:
        oc = outcomes[pol]
        lines.append(f"| {pol} | {cost[pol]:,.0f} | {oc['fraud_stopped']}/{n_fraud} ({oc['fraud_stopped']/n_fraud:.1%}) | "
                     f"{oc['legit_blocked'] + oc['legit_failed_stepup']} ({(oc['legit_blocked'] + oc['legit_failed_stepup'])/n_legit:.2%}) | "
                     f"{oc['legit_verified'] + oc['legit_failed_stepup']} | {actions[pol]['HOLD']} | "
                     + "/".join(str(actions[pol][a]) for a in ("ALLOW", "STEP_UP", "HOLD", "BLOCK")) + " |")

    ledger = shield.ledger
    ok, n_rec = ledger.verify()
    first = next(ledger.records())
    replay = ledger.replay(first["booking_id"], shield.model)
    tampered = ledger_path.read_text(encoding="utf-8").splitlines()
    tampered[5] = tampered[5].replace('"action":"', '"action":"X', 1)
    tmp = HERE / "ledger_dataco_tampered.jsonl"
    tmp.write_text("\n".join(tampered) + "\n", encoding="utf-8")
    ok_t, n_t = AuditLedger(tmp).verify()
    tmp.unlink()

    def top_reasons(i):
        return ", ".join(f"`{x['feature']}`={x['value'] if isinstance(x['value'], str) else format(x['value'], '.3g')} "
                         f"(+{x['contribution']:.2f})" for x in shield.reasons(X_rows[i]))
    i_f = int(np.argmax(np.where(y_te == 1, probs_a, -1))); i_l = int(np.argmax(np.where(y_te == 0, probs_a, -1)))

    # ------------------------------------------------------------------ stats for the dashboard
    pay = te.payment_type.values
    top_idx = np.argsort(-probs_a)[:12]
    monthly = o.groupby(o.ts.dt.to_period("M")).agg(orders=("is_fraud", "size"), fraud=("is_fraud", "sum"))
    t_only = o[o.payment_type == "TRANSFER"]
    monthly_t = t_only.groupby(t_only.ts.dt.to_period("M")).agg(orders=("is_fraud", "size"), fraud=("is_fraud", "sum"))
    stats = dict(
        window=dict(start=str(te.ts.min().date()), end=str(te.ts.max().date()), orders=len(te), fraud=n_fraud,
                    transfer_orders=int((pay == "TRANSFER").sum())),
        training=shield.training_summary,
        policies={pol: dict(cost_usd=round(cost[pol], 2), fraud_stopped=outcomes[pol]["fraud_stopped"],
                            legit_blocked=outcomes[pol]["legit_blocked"] + outcomes[pol]["legit_failed_stepup"],
                            legit_verified=outcomes[pol]["legit_verified"] + outcomes[pol]["legit_failed_stepup"],
                            reviews=actions[pol]["HOLD"], actions=dict(actions[pol])) for pol in POLICIES},
        live_actions_by_payment={pt: dict(Counter(a for a, q in zip(live_actions, pay) if q == pt))
                                 for pt in sorted(set(pay))},
        fraud_at_risk_usd=round(fraud_at_risk, 2), n_fraud=n_fraud, n_legit=n_legit,
        live_model=dict(all_auc=ev["all"]["roc_auc"], transfer_auc=ev["transfer"]["roc_auc"],
                        transfer_ci=ev["transfer"]["roc_ci"]),
        ambiguous=ambiguous,
        monthly=[dict(month=str(m), all_rate=float(r.fraud / r.orders),
                      transfer_rate=float(monthly_t.loc[m].fraud / monthly_t.loc[m].orders))
                 for m, r in monthly.iterrows()],
        top_orders=[dict(order_id=int(records[i]["order_id"]), p=float(probs_a[i]), action=live_actions[i],
                         payment=str(pay[i]), fraud=bool(y_te[i]), value=float(records[i]["net_total"]),
                         reasons=shield.reasons(X_rows[i], 3)) for i in top_idx],
        ledger=dict(records=n_rec, verified=ok, tamper_detected=not ok_t, tamper_at=n_t,
                    replay_reproduced=bool(replay["reproduced"]), replay_id=first["booking_id"]),
        experiments=experiment_headlines(),
    )
    (HERE / "stats_dataco.json").write_text(json.dumps(stats, indent=1, default=float), encoding="utf-8")
    (ROOT / "visuals" / "dashboard_dataco.html").write_text(render_dashboard_dataco(stats), encoding="utf-8")

    P.write(HERE / "results_dataco.md", f"""
# FraudShield replay on real data: DataCo, 2017-07 → 2018-01

Training: {len(tr)} orders (2015–2016). Calibration and conformal fit: 2017-H1, split in half.
Replay: {len(te)} orders ({n_fraud} fraud), in time order, through the live path. Model `{shield.model.version}`,
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
