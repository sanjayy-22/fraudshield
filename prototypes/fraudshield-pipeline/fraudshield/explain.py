"""Explanation service: evidence pack → narrative → grounding verifier → counterfactual.

Runs OFF the synchronous scoring path. The LLM (or the deterministic template) only
ever sees the evidence pack, and its output is rejected if it cites any number or
identifier that is not in the pack.
"""
from __future__ import annotations

import json
import os
import re

import numpy as np

from .rules import RULE_TEXT

# feature → (label, formatter, benign/typical value for counterfactual probing)
GLOSSARY = {
    "log_pay_age_min":  ("payment instrument age", lambda v: f"{np.expm1(v) / 60:.1f} h old" if np.expm1(v) < 1440 else f"{np.expm1(v) / 1440:.0f} days old", 13.0),
    "drift_score":      ("behavioural drift vs own history", lambda v: f"{v:.1f} (typical ≈ 4)", 4.0),
    "vel24_ratio":      ("24 h booking velocity vs baseline", lambda v: f"{v:.1f}× the usual daily rate", 1.0),
    "vel_1h":           ("bookings in the last hour", lambda v: f"{int(v)}", 0.0),
    "vel_24h":          ("bookings in the last 24 h", lambda v: f"{int(v)}", 1.0),
    "dev_shared_n":     ("other shippers on this device (30 d)", lambda v: f"{int(v)}", 0.0),
    "dev_fraud":        ("confirmed-fraud bookings on this device", lambda v: f"{int(v)}", 0.0),
    "dest_fanin_30d":   ("other shippers to this address (30 d)", lambda v: f"{int(v)}", 0.0),
    "dest_fanin_all":   ("other shippers to this address (ever)", lambda v: f"{int(v)}", 0.0),
    "dest_fraud":       ("confirmed-fraud shipments to this address", lambda v: f"{int(v)}", 0.0),
    "pay_shared_n":     ("other shippers on this payment instrument", lambda v: f"{int(v)}", 0.0),
    "pay_fraud":        ("confirmed-fraud bookings on this payment instrument", lambda v: f"{int(v)}", 0.0),
    "comp_fraud":       ("confirmed fraud in linked account cluster", lambda v: f"{int(v)}", 0.0),
    "comp_shippers":    ("accounts in linked cluster", lambda v: f"{int(v)}", 1.0),
    "comp_fraud_ratio": ("fraud density of linked account cluster", lambda v: f"{v:.2f} per account", 0.0),
    "dest_addr_nov":    ("destination novelty for this shipper", lambda v: f"{v:.1f} nats", 0.5),
    "dest_addr_seen":   ("destination seen before", lambda v: "yes" if v else "no", 1.0),
    "dest_city_nov":    ("destination-city novelty", lambda v: f"{v:.1f} nats", 0.5),
    "dest_city_seen":   ("destination city seen before", lambda v: "yes" if v else "no", 1.0),
    "origin_nov":       ("origin novelty", lambda v: f"{v:.1f} nats", 0.3),
    "origin_is_usual":  ("origin is the usual one", lambda v: "yes" if v else "no", 1.0),
    "service_nov":      ("service-type novelty", lambda v: f"{v:.1f} nats", 0.5),
    "contents_nov":     ("contents novelty", lambda v: f"{v:.1f} nats", 1.0),
    "hour_nov":         ("time-of-day novelty", lambda v: f"{v:.1f} nats", 2.5),
    "w_z":              ("weight vs shipper's history", lambda v: f"{v:+.1f} σ", 0.0),
    "val_z":            ("declared value vs history", lambda v: f"{v:+.1f} σ", 0.0),
    "log_weight":       ("log weight", lambda v: f"{np.exp(v):.1f} kg", None),
    "log_value":        ("log declared value", lambda v: f"₹{np.exp(v):,.0f}", None),
    "new_device":       ("new device", lambda v: "yes" if v else "no", 0.0),
    "new_payment":      ("new payment instrument", lambda v: "yes" if v else "no", 0.0),
    "days_since_last":  ("days since previous booking", lambda v: f"{v:.0f}", 3.0),
    "hour":             ("booking hour", lambda v: f"{int(v):02d}:00", 12.0),
    "is_express":       ("express/priority service", lambda v: "yes" if v else "no", 0.0),
    "n_hist":           ("historical bookings", lambda v: f"{int(v)}", None),
    "log_n_hist":       ("historical bookings (log)", lambda v: f"{int(np.expm1(v))}", None),
    "account_age_days": ("account age (days)", lambda v: f"{v:.0f}", None),
}
NUM_RE = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?")
ID_RE = re.compile(r"\b(?:B\d{6}|S\d{4}|R\d\d_[A-Z_]+|mule_\d+_\d+|dev_\w+|pay_\w+|addr_\w+|hub_\w+)\b")


def counterfactual(model, features: dict, threshold: float, candidates: list[str]) -> list[dict]:
    out = []
    for f in candidates:
        typ = GLOSSARY.get(f, (None, None, None))[2]
        if typ is None:
            continue
        f2 = dict(features); f2[f] = typ
        p2 = model.predict_one(f2)
        out.append(dict(feature=f, label=GLOSSARY[f][0], set_to=typ, p_after=round(p2, 4),
                        clears_threshold=bool(p2 < threshold)))
    return out


def evidence_pack(result: dict, model, threshold: float) -> dict:
    f = result["features"]
    c = model.contributions(f).sort_values(ascending=False)
    top = [k for k in c.index if c[k] > 0][:6]
    attributions = []
    for k in top:
        label, fmt, _ = GLOSSARY.get(k, (k, lambda v: f"{v:.2f}", None))
        attributions.append(dict(feature=k, label=label, value=float(f[k]), display=fmt(float(f[k])),
                                 contribution=round(float(c[k]), 3)))
    return dict(
        booking_id=result["booking_id"], shipper_id=result["shipper_id"], cohort=result["cohort"],
        p_fraud=round(result["p_fraud"], 4), threshold=round(threshold, 4), action=result["decision"]["action"],
        history_bookings=int(f["n_hist"]), attributions=attributions,
        rule_hits=[dict(code=h, text=RULE_TEXT[h]) for h in result["rules"]["hits"]],
        graph=dict(dest_other_shippers_30d=int(f["dest_fanin_30d"]), dest_confirmed_fraud=int(f["dest_fraud"]),
                   device_other_shippers=int(f["dev_shared_n"]), device_confirmed_fraud=int(f["dev_fraud"]),
                   payment_other_shippers=int(f["pay_shared_n"]), payment_confirmed_fraud=int(f["pay_fraud"]),
                   cluster_accounts=int(f["comp_shippers"]), cluster_confirmed_fraud=int(f["comp_fraud"])),
        conformal=result.get("conformal"),
        counterfactual=counterfactual(model, f, threshold, top[:4]),
    )


def narrative_analyst(ev: dict) -> str:
    """Deterministic template with the same contract as the LLM prompt: every number comes from ev."""
    parts = [f"Booking {ev['booking_id']} by shipper {ev['shipper_id']} ({ev['cohort']}) has a calibrated fraud "
             f"probability of {ev['p_fraud']:.3f}; action taken: {ev['action']}. The shipper has {ev['history_bookings']} "
             f"prior bookings on record."]
    if ev["attributions"]:
        parts.append("Main drivers — " + "; ".join(f"{a['label']}: {a['display']}" for a in ev["attributions"][:4]) + ".")
    if ev["rule_hits"]:
        parts.append("Policy rules triggered: " + "; ".join(f"{h['code']} ({h['text']})" for h in ev["rule_hits"]) + ".")
    g = ev["graph"]
    if g["dest_confirmed_fraud"] or g["device_confirmed_fraud"] or g["payment_confirmed_fraud"]:
        parts.append(f"Linked infrastructure: destination address has {g['dest_confirmed_fraud']} confirmed-fraud shipments, "
                     f"device {g['device_confirmed_fraud']}, payment instrument {g['payment_confirmed_fraud']}.")
    cf = [c for c in ev["counterfactual"] if c["clears_threshold"]]
    if cf:
        parts.append(f"It would score below threshold ({cf[0]['p_after']:.3f}) if the {cf[0]['label']} were at this "
                     f"shipper's typical level — that is the first thing to verify with the account owner.")
    if ev.get("conformal", {}).get("ambiguous"):
        parts.append("The model's conformal prediction set is ambiguous, so human review is worth its cost here.")
    return " ".join(parts)


def narrative_customer(ev: dict) -> str:
    """Customer-facing message: never reveals features or reasons (would coach fraudsters)."""
    if ev["action"] == "STEP_UP":
        return (f"To protect your account, please confirm booking {ev['booking_id']} using the verification link "
                "we sent to your registered contact details. This takes under a minute.")
    if ev["action"] == "HOLD":
        return (f"Booking {ev['booking_id']} is being reviewed by our team before pickup. We will confirm within "
                "the next few hours; no action is needed from you.")
    if ev["action"] == "BLOCK":
        return (f"We were unable to process booking {ev['booking_id']}. Please contact support with this reference "
                "so we can assist you.")
    return ""


def llm_prompt(ev: dict) -> str:
    """The contract for a real LLM. Plug any provider in behind narrative_llm()."""
    return ("You are a fraud analyst assistant for a parcel carrier. In 3–5 plain-English sentences, explain to an "
            "operations reviewer why this booking received its action. Use ONLY facts in the JSON evidence; never "
            "invent numbers, entities or reasons; quote numbers exactly as given. Finish with the single most useful "
            "counterfactual if one clears the threshold.\n\nEVIDENCE:\n" + json.dumps(ev, indent=1, default=str))


def narrative_llm(ev: dict) -> str | None:
    if not os.environ.get("FRAUDSHIELD_LLM"):
        return None
    raise NotImplementedError("wire your LLM client here using llm_prompt(ev)")


def verify_grounding(narrative: str, ev: dict) -> tuple[bool, list[str]]:
    """Every number and identifier in the narrative must appear in the evidence pack."""
    ev_text = json.dumps(ev, default=str)
    ev_nums = set()
    for n in NUM_RE.findall(ev_text):
        try:
            v = float(n)
        except ValueError:
            continue
        ev_nums.update({n, *(f"{v:.{d}f}" for d in range(5))})
    for a in ev.get("attributions", []):
        ev_nums.update(NUM_RE.findall(a["display"]))
    issues = []
    for n in NUM_RE.findall(narrative):
        v = float(n)
        if n not in ev_nums and not any(f"{v:.{d}f}" in ev_nums for d in range(5)):
            issues.append(f"number {n} not in evidence")
    ev_ids = set(ID_RE.findall(ev_text))
    for i in ID_RE.findall(narrative):
        if i not in ev_ids:
            issues.append(f"identifier {i} not in evidence")
    return (not issues), issues


def explain(result: dict, model, threshold: float) -> dict:
    ev = evidence_pack(result, model, threshold)
    text = None
    try:
        text = narrative_llm(ev)
    except NotImplementedError:
        text = None
    source = "llm"
    if text is None:
        text, source = narrative_analyst(ev), "template"
    ok, issues = verify_grounding(text, ev)
    if not ok and source == "llm":           # reject and fall back to the grounded template
        text, source = narrative_analyst(ev), "template-after-rejection"
        ok, issues = verify_grounding(text, ev)
    return dict(evidence=ev, analyst_narrative=text, customer_message=narrative_customer(ev),
                narrative_source=source, grounded=ok, verifier_issues=issues)
