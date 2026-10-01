"""End-to-end demo: train on the first 70 % of the simulated stream, then replay the last
30 % booking-by-booking through the live scoring path.

For every booking the LIVE policy (cost-sensitive + conformal-gated review) decides; two
challenger policies (fixed threshold at 1 % FPR, and a two-threshold review band) are
evaluated in shadow on the same probabilities. Realised costs use the true labels and the
outcome model in decision.py (step-up pass rates, analyst catch rate).

Outputs
  results.md            metrics, policy comparison, sample explanations, ledger check
  stats.json            everything the dashboard renders
  ../../visuals/dashboard.html
  ledger.jsonl          hash-chained decision log
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "prototypes" / "data"))
from simulate import generate                                                  # noqa: E402
from fraudshield.pipeline import FraudShield                                   # noqa: E402
from fraudshield.decision import (CostParams, ReviewCapacity, fixed_threshold,   # noqa: E402
                                  banded, realized_cost, unit_costs)
from dashboard import render_dashboard                                          # noqa: E402

OUTCOME_TO_FEEDBACK = {
    "fraud_stopped": "confirmed_fraud", "legit_verified": "verified_legit", "legit_reviewed": "verified_legit",
    "fraud_missed_review": "verified_legit", "fraud_passed_stepup": "verified_legit",   # the system was fooled
    # a blocked legitimate customer contacts support and is verified there (the churn cost was already charged)
    "legit_blocked": "verified_legit", "legit_failed_stepup": "verified_legit",
    "fraud_shipped": "unknown", "legit_ok": "unknown",
}


def main(seed: int = 7):
    df = generate(seed=seed)
    cut = df.ts.quantile(0.70)
    history, stream = df[df.ts < cut], df[df.ts >= cut]
    ledger_path = HERE / "ledger.jsonl"
    if ledger_path.exists():
        ledger_path.unlink()

    fs = FraudShield(ledger_path=ledger_path, review_capacity=ReviewCapacity(per_window=2, window_hours=4))
    fs.fit(history)
    cp = fs.cp
    thr1, thr05, thr2 = fs.thresholds["fpr_1pct"], fs.thresholds["fpr_0_5pct"], fs.thresholds["fpr_2pct"]
    print("trained:", fs.training_summary, "thresholds:", {k: round(v, 4) for k, v in fs.thresholds.items()})

    rng = np.random.default_rng(seed)
    shadow_caps = {"two-threshold": ReviewCapacity(per_window=2, window_hours=4)}
    policies = ["cost-sensitive (live)", "fixed threshold @1% FPR", "two-threshold + review band"]
    cost = {p: 0.0 for p in policies}
    outcomes = {p: Counter() for p in policies}
    actions = {p: Counter() for p in policies}
    fraud_at_risk = 0.0
    daily = defaultdict(lambda: dict(fraud=0, stopped=0, legit=0, friction=0))
    results, latencies = [], []
    scenario_recall = defaultdict(lambda: [0, 0])

    for b in stream.to_dict("records"):
        r = fs.score(b)
        latencies.append(r["latency_ms"])
        y = bool(b["is_fraud"])
        u = unit_costs(b["charge_inr"], b["ltv"], cp)
        if y:
            fraud_at_risk += u["L"]
        hard = r["rules"]["hard_block"]
        decisions = {
            policies[0]: r["decision"]["action"],
            policies[1]: fixed_threshold(r["p_fraud"], thr1, hard).action,
            policies[2]: banded(r["p_fraud"], thr2, thr05, shadow_caps["two-threshold"], b["ts"], hard).action,
        }
        live_outcome = None
        for pol, act in decisions.items():
            c, out = realized_cost(act, y, b["charge_inr"], b["ltv"], cp, rng)
            cost[pol] += c
            outcomes[pol][out] += 1
            actions[pol][act] += 1
            if pol == policies[0]:
                live_outcome = out
        day = str(pd.Timestamp(b["ts"]).date())
        if y:
            daily[day]["fraud"] += 1
            daily[day]["stopped"] += int(live_outcome == "fraud_stopped")
            scenario_recall[b["scenario"]][1] += 1
            scenario_recall[b["scenario"]][0] += int(live_outcome == "fraud_stopped")
        else:
            daily[day]["legit"] += 1
            daily[day]["friction"] += int(live_outcome in ("legit_blocked", "legit_failed_stepup", "legit_verified", "legit_reviewed"))
        fs.feedback(b, OUTCOME_TO_FEEDBACK[live_outcome])
        r["is_fraud"] = int(y); r["scenario"] = b["scenario"]; r["live_outcome"] = live_outcome
        results.append(r)

    # ------------------------------------------------------------------ summaries
    n_fraud, n_legit = int(stream.is_fraud.sum()), int((stream.is_fraud == 0).sum())
    rows = []
    for pol in policies:
        o = outcomes[pol]
        stopped = o["fraud_stopped"]
        friction = o["legit_blocked"] + o["legit_failed_stepup"]
        stepped = o["legit_verified"] + o["legit_failed_stepup"]
        reviewed = o["legit_reviewed"] + sum(v for k, v in o.items() if k in ("fraud_stopped",) and actions[pol]["HOLD"])  # approx
        rows.append({"policy": pol, "realised cost ₹": round(cost[pol]), "fraud stopped": f"{stopped}/{n_fraud}",
                     "fraud stopped %": round(100 * stopped / n_fraud, 1),
                     "legit blocked": friction, "legit blocked %": round(100 * friction / n_legit, 2),
                     "legit asked to verify": stepped, "reviews": actions[pol]["HOLD"],
                     "ALLOW/STEP_UP/HOLD/BLOCK": "/".join(str(actions[pol][a]) for a in ("ALLOW", "STEP_UP", "HOLD", "BLOCK"))})
    comp = pd.DataFrame(rows)
    baseline = fraud_at_risk
    lat = np.array(latencies)
    lat_stats = dict(p50=float(np.percentile(lat, 50)), p95=float(np.percentile(lat, 95)), p99=float(np.percentile(lat, 99)), max=float(lat.max()))

    # sample explanations: one caught fraud, one step-up, one held legit
    samples = []
    def pick(cond):
        for r in results:
            if cond(r):
                return r
    picks = [("caught fraud (BLOCK)", pick(lambda r: r["is_fraud"] and r["decision"]["action"] == "BLOCK")),
             ("fraud sent to step-up", pick(lambda r: r["is_fraud"] and r["decision"]["action"] == "STEP_UP")),
             ("legitimate booking held for review", pick(lambda r: not r["is_fraud"] and r["decision"]["action"] == "HOLD")),
             ("legitimate high-value account, stepped-up instead of blocked", pick(lambda r: not r["is_fraud"] and r["decision"]["action"] == "STEP_UP" and r["ltv"] >= 60000))]
    for label, r in picks:
        if r is None:
            continue
        ex = fs.explain(r)
        samples.append((label, r, ex))

    ok, n_rec = fs.ledger.verify()
    replay = fs.ledger.replay(results[0]["booking_id"], fs.model)
    # tamper test on a copy
    tampered = ledger_path.read_text(encoding="utf-8").splitlines()
    tampered[5] = tampered[5].replace('"action":"', '"action":"X')
    tmp = HERE / "ledger_tampered.jsonl"; tmp.write_text("\n".join(tampered) + "\n", encoding="utf-8")
    from fraudshield.ledger import AuditLedger
    ok_t, n_t = AuditLedger(tmp).verify(); tmp.unlink()

    # cost-sensitivity: how the live decision changes with customer value at a fixed p
    from fraudshield.decision import expected_costs, cheapest
    sens = []
    for charge in (300.0, 3000.0):
        for p in (0.02, 0.1, 0.3, 0.6, 0.9, 0.99):
            for cohort, ltv in (("individual", 2000), ("sme", 60000), ("ecommerce", 300000)):
                e = expected_costs(p, charge, ltv, cp, True)
                sens.append(dict(charge=f"₹{charge:,.0f}", p=p, cohort=cohort, action=cheapest(e)))
    sens_tbl = pd.DataFrame(sens).pivot(index=["charge", "p"], columns="cohort", values="action")[["individual", "sme", "ecommerce"]]

    scen_tbl = pd.DataFrame([{"scenario": k, "stopped": v[0], "n": v[1], "recall": round(v[0] / v[1], 2)} for k, v in sorted(scenario_recall.items())])

    stats = dict(
        n_stream=len(stream), n_fraud=n_fraud, n_legit=n_legit, fraud_at_risk=round(baseline),
        policies=rows, latency_ms=lat_stats, daily=[dict(day=k, **v) for k, v in sorted(daily.items())],
        actions_live={a: actions[policies[0]][a] for a in ("ALLOW", "STEP_UP", "HOLD", "BLOCK")},
        actions_by_cohort={c: {a: sum(1 for r in results if r["cohort"] == c and r["decision"]["action"] == a) for a in ("ALLOW", "STEP_UP", "HOLD", "BLOCK")} for c in ("individual", "sme", "ecommerce")},
        scenario_recall=scen_tbl.to_dict("records"), ledger=dict(valid=ok, records=n_rec, tamper_detected=not ok_t, tamper_broke_at=n_t, replay=replay),
        sensitivity=sens_tbl.reset_index().to_dict("records"), training=fs.training_summary,
        thresholds={k: round(v, 4) for k, v in fs.thresholds.items()},
        top_p=[dict(booking_id=r["booking_id"], p=round(r["p_fraud"], 3), action=r["decision"]["action"], fraud=r["is_fraud"], scenario=r["scenario"]) for r in sorted(results, key=lambda r: -r["p_fraud"])[:15]],
        samples=[dict(label=l, booking_id=r["booking_id"], narrative=e["analyst_narrative"], customer=e["customer_message"], grounded=e["grounded"]) for l, r, e in samples],
    )
    (HERE / "stats.json").write_text(json.dumps(stats, indent=1, default=str), encoding="utf-8")
    (ROOT / "visuals" / "dashboard.html").write_text(render_dashboard(stats), encoding="utf-8")

    md = ["# FraudShield pipeline — live replay results", "",
          f"History: {len(history)} bookings → model `{fs.training_summary['model_version']}` "
          f"(train {fs.training_summary['train']}, {fs.training_summary['train_fraud']} fraud; Platt calibration on "
          f"{fs.training_summary['calib']}; conformal on {fs.training_summary['conformal']}). "
          f"Live stream: {len(stream)} bookings, {n_fraud} fraud, from {stream.ts.min().date()} to {stream.ts.max().date()}.", "",
          f"Fraud loss at risk if nothing is detected: **₹{baseline:,.0f}** (charge × 1.6 over all fraud bookings).", "",
          "## Policy comparison (same probabilities, realised cost with true labels)", "",
          comp.to_markdown(index=False), "",
          "Realised cost includes fraud that shipped, revenue and churn from blocking legitimate customers, step-up "
          "friction, and analyst time. Lower is better.", "",
          "## Recall by fraud scenario (live policy, stopped before shipping)", "", scen_tbl.to_markdown(index=False), "",
          "## Same probability, different customer → different action", "",
          "Live policy at each fraud probability, by shipment charge and customer value (no hard rule, review capacity available):", "",
          sens_tbl.reset_index().to_markdown(index=False), "",
          "## Latency of the synchronous path (features + rules + model + conformal + decision + ledger write)", "",
          f"p50 {lat_stats['p50']:.2f} ms · p95 {lat_stats['p95']:.2f} ms · p99 {lat_stats['p99']:.2f} ms · max {lat_stats['max']:.2f} ms "
          "(single Python process, in-memory store; no network hops).", "",
          "## Audit ledger", "",
          f"- chain valid: **{ok}** over {n_rec} records; tampering one field of record 5 is detected: **{not ok_t}** (chain breaks at record {n_t})",
          f"- replay of `{replay.get('stored_p') is not None and results[0]['booking_id']}`: stored p = {replay['stored_p']:.6f}, "
          f"re-scored p = {replay['replayed_p']:.6f}, reproduced = **{replay['reproduced']}**", "",
          "## Sample explanations (generated off the decision path, verified for grounding)", ""]
    for label, r, ex in samples:
        md += [f"### {label} — {r['booking_id']} (p = {r['p_fraud']:.3f}, {r['decision']['action']}, true: {'fraud' if r['is_fraud'] else 'legit'})", "",
               f"**Analyst:** {ex['analyst_narrative']}", "", f"**Customer:** {ex['customer_message'] or '—'}", "",
               f"Grounding verifier: {'PASS' if ex['grounded'] else 'FAIL ' + str(ex['verifier_issues'])}", ""]
    md += ["## Notes", "",
           "- The live policy's HOLD is gated by the conformal prediction set: analysts only see bookings the model",
           "  declares ambiguous at 90 % confidence, so the review budget is spent where it changes outcomes.",
           "- Feedback closes the loop immediately: a failed step-up is a confirmed-fraud label within a day, blocked",
           "  bookings never poison the shipper's behavioural profile, and the graph learns the mule address at once.",
           "- Challenger policies are scored in shadow on the same probabilities — the champion/challenger mechanism",
           "  a production system would use to roll out a new policy version safely.", ""]
    (HERE / "results.md").write_text("\n".join(md), encoding="utf-8")
    print(comp.to_string(index=False))
    print(scen_tbl.to_string(index=False))
    print("latency", {k: round(v, 2) for k, v in lat_stats.items()}, "| ledger valid:", ok, "tamper detected:", not ok_t, "| replay:", replay["reproduced"])
    return stats


if __name__ == "__main__":
    main()
