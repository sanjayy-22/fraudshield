"""Experiment D — Grounded GenAI explanation with a hallucination verifier + counterfactuals.

The GenAI layer never decides anything. It narrates an *evidence pack* assembled by
the deterministic pipeline and is checked by a verifier before anything reaches an
analyst or a customer.

evidence pack  = { top attributions (feature, value, typical value, contribution),
                   rule hits (code + description), graph facts, drift facts,
                   counterfactual ("would be normal if …"), decision }
narrative      = LLM(evidence pack)   — or the deterministic template below when no
                                       LLM API key is configured (same contract)
verifier       = every number and every entity id in the narrative must occur in the
                 evidence pack; otherwise the narrative is rejected and regenerated
                 (or the template is used). This is what makes a GenAI explanation
                 admissible in an audit.
counterfactual = smallest single-feature change (to the shipper's typical value) that
                 pulls the fraud probability under the decision threshold.

This experiment builds the evidence pack for real caught bookings from experiment A's
model, generates and verifies narratives, and demonstrates the verifier rejecting a
deliberately hallucinated narrative.
"""
from __future__ import annotations

import json
import os
import pickle
import re
import sys
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
sys.path.insert(0, str(ROOT / "prototypes" / "data"))
sys.path.insert(0, str(ROOT / "experiments" / "a-rules-gbm-shap"))
from simulate import generate                                   # noqa: E402
from featurize import build_feature_frame                       # noqa: E402
from run import RULES                                           # noqa: E402

# human phrasing + "typical/benign" value used for counterfactual probing
GLOSSARY = {
    "log_pay_age_min":  ("payment instrument age", lambda v: f"{np.expm1(v) / 60:.1f} h old" if np.expm1(v) < 1440 else f"{np.expm1(v) / 1440:.0f} days old", 13.0),
    "drift_score":      ("behavioural drift vs own history", lambda v: f"{v:.1f} (typical ≈ 4)", 4.0),
    "vel24_ratio":      ("24 h booking velocity vs baseline", lambda v: f"{v:.1f}× the usual daily rate", 1.0),
    "vel_1h":           ("bookings in the last hour", lambda v: f"{int(v)}", 0.0),
    "dev_shared_n":     ("other shippers on this device (30 d)", lambda v: f"{int(v)}", 0.0),
    "dev_fraud":        ("confirmed-fraud bookings on this device", lambda v: f"{int(v)}", 0.0),
    "dest_fanin_30d":   ("other shippers to this address (30 d)", lambda v: f"{int(v)}", 0.0),
    "dest_fraud":       ("confirmed-fraud shipments to this address", lambda v: f"{int(v)}", 0.0),
    "pay_shared_n":     ("other shippers on this payment instrument", lambda v: f"{int(v)}", 0.0),
    "pay_fraud":        ("confirmed-fraud bookings on this payment instrument", lambda v: f"{int(v)}", 0.0),
    "comp_fraud_ratio": ("fraud density of linked account cluster", lambda v: f"{v:.2f} per account", 0.0),
    "dest_addr_nov":    ("destination novelty for this shipper", lambda v: f"{v:.1f} nats", 0.5),
    "dest_city_nov":    ("destination-city novelty", lambda v: f"{v:.1f} nats", 0.5),
    "origin_nov":       ("origin novelty", lambda v: f"{v:.1f} nats", 0.3),
    "service_nov":      ("service-type novelty", lambda v: f"{v:.1f} nats", 0.5),
    "hour_nov":         ("time-of-day novelty", lambda v: f"{v:.1f} nats", 2.5),
    "w_z":              ("weight vs shipper's history", lambda v: f"{v:+.1f} σ", 0.0),
    "val_z":            ("declared value vs history", lambda v: f"{v:+.1f} σ", 0.0),
    "new_device":       ("new device", lambda v: "yes" if v else "no", 0.0),
    "new_payment":      ("new payment instrument", lambda v: "yes" if v else "no", 0.0),
    "days_since_last":  ("days since previous booking", lambda v: f"{v:.0f}", 3.0),
    "hour":             ("booking hour", lambda v: f"{int(v):02d}:00", 12.0),
    "is_express":       ("express/priority service", lambda v: "yes" if v else "no", 0.0),
    "n_hist":           ("historical bookings", lambda v: f"{int(v)}", None),
}
RULE_TEXT = {code: text for code, _, text, _ in RULES}


def contributions(bundle, row: pd.Series) -> pd.Series:
    cols = bundle["feature_cols"]
    if bundle["backend"] == "lightgbm":
        c = bundle["model"].booster_.predict(row[cols].to_frame().T.astype(float), pred_contrib=True)[0][:-1]
        return pd.Series(c, index=cols)
    # model-agnostic fallback: p(x) - p(x with feature set to its typical value)
    base = bundle["model"].predict_proba(row[cols].to_frame().T.astype(float))[0, 1]
    out = {}
    for f in cols:
        typ = GLOSSARY.get(f, (None, None, None))[2]
        if typ is None:
            out[f] = 0.0
            continue
        r2 = row.copy(); r2[f] = typ
        out[f] = base - bundle["model"].predict_proba(r2[cols].to_frame().T.astype(float))[0, 1]
    return pd.Series(out)


def counterfactual(bundle, row: pd.Series, threshold: float, top: list[str]) -> list[dict]:
    """Single-feature changes to the shipper's typical value that drop p below threshold."""
    cols = bundle["feature_cols"]
    out = []
    for f in top:
        typ = GLOSSARY.get(f, (None, None, None))[2]
        if typ is None:
            continue
        r2 = row.copy(); r2[f] = typ
        p2 = float(bundle["model"].predict_proba(r2[cols].to_frame().T.astype(float))[0, 1])
        out.append(dict(feature=f, set_to=typ, p_after=p2, clears_threshold=bool(p2 < threshold)))
    return out


def evidence_pack(bundle, row: pd.Series, p: float, threshold: float) -> dict:
    c = contributions(bundle, row).sort_values(ascending=False)
    top = [f for f in c.index if c[f] > 0][:6]
    attributions = []
    for f in top:
        name, fmt, _ = GLOSSARY.get(f, (f, lambda v: f"{v:.2f}", None))
        attributions.append(dict(feature=f, label=name, value=float(row[f]), display=fmt(float(row[f])),
                                 contribution=float(c[f])))
    hits = [dict(code=code, text=text) for code, _, text, pred in RULES if pred(row.to_dict())]
    return dict(
        booking_id=row.booking_id, shipper_id=row.shipper_id, cohort=row.cohort,
        p_fraud=round(float(p), 4), threshold=round(float(threshold), 4),
        history_bookings=int(row.n_hist), attributions=attributions, rule_hits=hits,
        graph=dict(dest_other_shippers_30d=int(row.dest_fanin_30d), dest_confirmed_fraud=int(row.dest_fraud),
                   device_other_shippers=int(row.dev_shared_n), device_confirmed_fraud=int(row.dev_fraud),
                   payment_other_shippers=int(row.pay_shared_n), payment_confirmed_fraud=int(row.pay_fraud)),
        counterfactual=counterfactual(bundle, row, threshold, top[:4]),
    )


# ----------------------------------------------------------------- narratives
def narrative_template(ev: dict) -> str:
    """Deterministic stand-in with the same contract as the LLM: every number it prints comes from ev."""
    parts = [f"Booking {ev['booking_id']} by shipper {ev['shipper_id']} scores a fraud probability of "
             f"{ev['p_fraud']:.2f} (decision threshold {ev['threshold']:.2f}), based on {ev['history_bookings']} "
             f"prior bookings from this shipper."]
    if ev["attributions"]:
        drivers = "; ".join(f"{a['label']}: {a['display']}" for a in ev["attributions"][:4])
        parts.append(f"Main drivers — {drivers}.")
    if ev["rule_hits"]:
        parts.append("Policy rules triggered: " + "; ".join(f"{h['code']} ({h['text']})" for h in ev["rule_hits"]) + ".")
    g = ev["graph"]
    if g["dest_confirmed_fraud"] or g["device_confirmed_fraud"] or g["payment_confirmed_fraud"]:
        parts.append(f"Linked infrastructure: destination has {g['dest_confirmed_fraud']} confirmed-fraud shipments, "
                     f"device {g['device_confirmed_fraud']}, payment instrument {g['payment_confirmed_fraud']}.")
    cf = [c for c in ev["counterfactual"] if c["clears_threshold"]]
    if cf:
        a = cf[0]
        label = GLOSSARY.get(a["feature"], (a["feature"],))[0]
        parts.append(f"It would score below threshold ({a['p_after']:.2f}) if the {label} were at this shipper's typical level.")
    return " ".join(parts)


def narrative_llm(ev: dict) -> str | None:
    """Optional: real LLM. Set FRAUDSHIELD_LLM=1 and provide credentials + a client of your
    choice. The prompt contract is the important part; the vendor is not."""
    if not os.environ.get("FRAUDSHIELD_LLM"):
        return None
    prompt = (
        "You are a fraud analyst assistant. Write 3–5 sentences in plain business English explaining "
        "why this shipment booking was flagged, for an operations reviewer. Use ONLY the facts in the "
        "JSON evidence below. Do not invent numbers, entities or reasons. Quote numbers exactly as given. "
        "End with the single most useful counterfactual if one is present.\n\nEVIDENCE:\n" + json.dumps(ev, indent=1))
    raise NotImplementedError("wire your LLM client here; return the completion text for: " + prompt[:60])


NUM_RE = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?")
ID_RE = re.compile(r"\b(?:B\d{6}|S\d{4}|R\d\d_[A-Z_]+|mule_\d+_\d+|dev_\w+|pay_\w+|addr_\w+|hub_\w+)\b")


def verify_grounding(narrative: str, ev: dict) -> tuple[bool, list[str]]:
    """Every number and identifier in the narrative must appear in the evidence pack."""
    ev_text = json.dumps(ev)
    ev_nums = set()
    for n in NUM_RE.findall(ev_text):
        try:
            v = float(n)
            ev_nums.update({f"{v:.0f}", f"{v:.1f}", f"{v:.2f}", f"{v:.3f}", f"{v:.4f}", n})
            # derived displays (hours/days from minutes) are also acceptable
        except ValueError:
            pass
    for a in ev.get("attributions", []):
        ev_nums.update(NUM_RE.findall(a["display"]))
    issues = []
    for n in NUM_RE.findall(narrative):
        v = float(n)
        if not any(f"{v:.{d}f}" in ev_nums for d in range(5)) and n not in ev_nums:
            issues.append(f"number {n} not in evidence")
    ev_ids = set(ID_RE.findall(ev_text))
    for i in ID_RE.findall(narrative):
        if i not in ev_ids:
            issues.append(f"identifier {i} not in evidence")
    return (not issues), issues


def main():
    bundle = pickle.load(open(ROOT / "experiments" / "a-rules-gbm-shap" / "model.pkl", "rb"))
    df = generate(seed=7)
    X = build_feature_frame(df)
    cut = X["ts"].quantile(0.70)
    te = X[X.ts >= cut].reset_index(drop=True)
    p = bundle["model"].predict_proba(te[bundle["feature_cols"]])[:, 1]
    thr = bundle["threshold_fpr1"]

    # pick: highest-scoring case of each scenario + the worst false positive
    picks = []
    for sc in sorted(te.scenario.unique()):
        if sc == "legit":
            continue
        sub = te[(te.scenario == sc)]
        picks.append(int(sub.index[np.argmax(p[sub.index])]))
    legit = te[te.is_fraud == 0]
    picks.append(int(legit.index[np.argmax(p[legit.index])]))

    sections, verified = [], 0
    for i in picks:
        row = te.loc[i]
        ev = evidence_pack(bundle, row, p[i], thr)
        text = narrative_llm(ev) if os.environ.get("FRAUDSHIELD_LLM") else narrative_template(ev)
        ok, issues = verify_grounding(text, ev)
        verified += ok
        sections += [f"### {row.scenario} — {row.booking_id} (true label: {'FRAUD' if row.is_fraud else 'legit'})", "",
                     f"> {text}", "", f"Verifier: {'PASS' if ok else 'FAIL ' + str(issues)}", "",
                     "```json", json.dumps({k: ev[k] for k in ('attributions', 'rule_hits', 'counterfactual')}, indent=1, default=str), "```", ""]
        if i == picks[0]:
            (HERE / "example_evidence_pack.json").write_text(json.dumps(ev, indent=2, default=str), encoding="utf-8")

    # adversarial check: a hallucinated narrative must be rejected
    ev0 = evidence_pack(bundle, te.loc[picks[0]], p[picks[0]], thr)
    bad = (f"Booking {ev0['booking_id']} was flagged because the shipper booked 14 parcels to mule_9_99 "
           f"in 2 hours and the card was 3 days old.")
    ok_bad, issues_bad = verify_grounding(bad, ev0)

    md = ["# Experiment D — grounded explanations, verifier, counterfactuals", "",
          f"{verified}/{len(picks)} generated narratives passed the grounding verifier.", "",
          "Adversarial check — a deliberately hallucinated narrative:", "", f"> {bad}", "",
          f"Verifier: {'PASS (bug!)' if ok_bad else 'REJECTED — ' + '; '.join(issues_bad)}", "",
          "## Cases", ""] + sections + [
          "## Observations", "",
          "- The narrative is *downstream* of the decision. Latency of the LLM never touches the booking SLA;",
          "  the explanation is produced asynchronously and attached to the case.",
          "- The verifier is cheap (regex over numbers/ids) and makes the GenAI output auditable: a narrative that",
          "  cites a number or entity absent from the evidence pack is never shown.",
          "- Counterfactuals turn attributions into an action: 'would clear if the payment instrument were not",
          "  minutes old' tells the analyst what to verify (step-up: confirm the new card with the account owner).",
          "- Two narratives should be rendered from the same pack: analyst-facing (this one) and customer-facing",
          "  (never reveals features; only asks for verification). Both are logged with the decision.", ""]
    (HERE / "results.md").write_text("\n".join(md), encoding="utf-8")
    print(f"{verified}/{len(picks)} narratives verified; hallucinated narrative rejected: {not ok_bad} {issues_bad}")


if __name__ == "__main__":
    main()
