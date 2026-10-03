"""Guided demo: six chapters that each show one component of the prototype, run automatically.

Every chapter calls the same desk methods the order form and the team-review screen use
(`desk.create`, `desk.review`, `desk.verify`), so nothing here is a mock-up. Each step reports which
layer made the decision: the ML model (with the cost policy), the expert rules, a person, or the customer.

    1 ml_model    the LightGBM model on its own (order details + customer history)
    2 rules       one expert rule at a time
    3 adds_up     three medium rules add up past the 85% fraud line
    4 feedback    team review → confirmed fraud → the same card is stopped for another customer
    5 verify      step-up: wrong code, then right code
    6 explain     plain-language explanation + audit-log check

Chapter 1 uses a fixed booking time (11:00 on the demo clock), and the rule chapters use the fixed times in
demo_scenarios.py, so the results do not depend on when the demo is run. Reset the desk between rehearsals.
"""
from __future__ import annotations

import copy
import os

from . import demo_scenarios as D
from . import genai
from .bookings import THRESHOLDS

EVERYDAY = dict(customer_id=12366, order_country="El Salvador", order_city="San Salvador", shipping_mode="First Class",
                items=[dict(product_id=957, quantity=1, discount_rate=0.05), dict(product_id=365, quantity=3, discount_rate=0.1)])
DISCOUNTED = dict(customer_id=16106, order_country="Países Bajos", order_city="Almelo", shipping_mode="Second Class",
                  payment_type="TRANSFER", items=[dict(product_id=276, quantity=3, discount_rate=0),
                                                   dict(product_id=172, quantity=5, discount_rate=0.25)])
CH4_CARD = "CARD-NEW-5522"

CHAPTERS = [
    dict(key="ml_model", title="The ML model on its own", component="LightGBM model · cost policy · model certainty",
         about="The model was trained on 65,752 real orders. It reads the order details and the customer's history. "
               "Below 30% overall risk, it decides on its own."),
    dict(key="rules", title="One rule at a time", component="Expert rules · weights",
         about="Signals the dataset does not contain (bursts, new cards, fraud addresses) are covered by expert rules. "
               "Each rule has a weight; some always stop an order."),
    dict(key="adds_up", title="Rules add up", component="Cumulative risk · the 85% fraud line",
         about="No single rule here is enough to stop the order. Together they pass the 85% line."),
    dict(key="feedback", title="People in the loop, and learning", component="Team review · confirmed fraud · feedback",
         about="A person rejects a suspicious order. The card it used is now known fraud, so the next order with that card "
               "is stopped, even from a different customer."),
    dict(key="verify", title="Verification", component="Step-up with a one-time code",
         about="Medium risk does not block the customer. They prove it's them with a code; three wrong codes stop the order."),
    dict(key="explain", title="Explain and audit", component="Plain-language explanation · hash-chained audit log",
         about="Every decision can be explained in simple words and is recorded in an audit log that shows tampering."),
]
BY_KEY = {c["key"]: c for c in CHAPTERS}


def _at(desk, hour: int) -> str:
    return str(D._plan(desk, hour))


def layer(b) -> str:
    """Which part of the system made the (first) decision."""
    if any(h["hard"] for h in b.rules_matched):
        return "expert rule (always stops)"
    if b.overall_risk >= THRESHOLDS["verify"]:
        return "expert rules"
    return "ML model"


def _step(label: str, b, pointers: list[str], extra_layer: str | None = None) -> dict:
    return dict(label=label, booking=copy.deepcopy(b.public(include_code=True)), decided_by=extra_layer or layer(b),
                pointers=pointers)


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


# ------------------------------------------------------------------ chapters
def ml_model(desk) -> list[dict]:
    at = _at(desk, 11)
    card = desk.create(EVERYDAY | dict(payment_type="DEBIT", book_at=at))
    transfer = desk.create(EVERYDAY | dict(payment_type="TRANSFER", book_at=at))
    disc = desk.create(DISCOUNTED | dict(book_at=at))
    return [
        _step("Returning customer pays by card", card, [
            f"Model risk {_pct(card.model_risk)}. In the real data, card orders were never fraud.",
            "No rule matched, so the model and the cost policy approved it."]),
        _step("The same order, paid by bank transfer", transfer, [
            f"Model risk rises to {_pct(transfer.model_risk)}: every fraud case in the data was a bank transfer.",
            "The model can't tell genuine from fraud with 90% confidence, so it asks a person (team review)."]),
        _step("Big discounted bank transfer", disc, [
            f"Model risk {_pct(disc.model_risk)}: the order looks like past fraud cases.",
            "Checking with the customer costs less than the risk, so the model asks for a one-time code."]),
    ]


def rules(desk) -> list[dict]:
    out = []
    for key, label in [("burst", "Booking burst"), ("new_card", "New card, new place, express"),
                       ("mule_address", "Known fraud address")]:
        prep = D.prepare(desk, key)
        b = desk.create(prep["form"])
        h = b.rules_matched[-1] if b.rules_matched else None
        pts = list(prep["notes"])
        if h:
            pts.append(f"Rule \"{h['name']}\" ({h['weight'] * 100:.0f}%) takes the risk from {_pct(h['before'])} to {_pct(h['after'])}.")
        out.append(_step(label, b, pts))
    return out


def adds_up(desk) -> list[dict]:
    prep = D.prepare(desk, "card_device_night")
    b = desk.create(prep["form"])
    chain = " → ".join(_pct(s["after"]) for s in b.risk_steps)
    desk._tour_ref = b.booking_id
    return [_step("New card + fraud-linked device + night", b, prep["notes"] + [
        f"Risk climbs {chain}. Each rule adds its share of the risk that is left.",
        f"{_pct(b.overall_risk)} is above the {THRESHOLDS['stop']:.0%} fraud line, so the order is stopped."])]


def feedback(desk) -> list[dict]:
    prep = D.prepare(desk, "new_card")
    form = prep["form"]
    form["signals"] = dict(form["signals"], payment_id=CH4_CARD)
    first = desk.create(form)
    held = _step("1. Order with a brand-new card", first, [f"Card {CH4_CARD} was added 20 minutes ago; same-day delivery to a new city.",
                                                          "The rules send it to the fraud team."])
    rejected = desk.review(first.booking_id, approve=False, note="customer says they did not place this order")
    reject = _step("2. The fraud team rejects it", rejected, [
        "The analyst confirms it is fraud.", f"Card {CH4_CARD} is now recorded as known fraud."], extra_layer="a person")
    other = D.prepare(desk, "heavy")                      # a different, clean demo customer
    f2 = other["form"]
    f2["signals"] = dict(payment_id=CH4_CARD, payment_added_minutes_ago=4320)
    second = desk.create(f2)
    again = _step("3. Another customer uses the same card", second, [
        f"Customer {second.customer_id} has a clean history and an ordinary parcel.",
        "The card is known fraud now, so the \"Payment method linked to fraud\" rule always stops it."])
    return [held, reject, again]


def verify(desk) -> list[dict]:
    prep = D.prepare(desk, "heavy")
    b = desk.create(prep["form"])
    first = _step("1. Parcel much heavier than usual", b, prep["notes"] + ["Medium risk: the customer is asked for a code."])
    code = b.verification_code
    wrong = desk.verify(b.booking_id, "000000" if code != "000000" else "111111")
    second = _step("2. The customer types a wrong code", wrong, [f"{wrong.attempts_left} tries left. Three wrong codes stop the order as fraud."],
                   extra_layer="the customer")
    right = desk.verify(b.booking_id, code)
    third = _step("3. The customer types the right code", right, [f"Approved with tracking number {right.tracking_id}.",
                                                                 "This parcel weight now counts as normal for this customer."],
                  extra_layer="the customer")
    return [first, second, third]


def explain(desk) -> list[dict]:
    ref = getattr(desk, "_tour_ref", None)
    if ref is None or ref not in desk.bookings:
        adds_up(desk)
        ref = desk._tour_ref
    b = desk.get(ref)
    x = genai.explain(b, THRESHOLDS, use_llm=os.environ.get("FRAUDSHIELD_LLM", "1") != "0")
    ok, n = desk.shield.ledger.verify() if desk.shield.ledger else (False, 0)
    step = _step("Explanation of the stopped order from chapter 3", b, [
        ("Written by AI; every number was checked against the facts." if x["source"] == "ai"
         else f"Standard explanation (AI not used: {x['note']})."),
        f"Audit log: {n} records, chain {'valid' if ok else 'BROKEN'}. Changing any record would break the chain."])
    step["explanation"] = dict(text=x["text"], source=x["source"], note=x["note"])
    step["audit"] = dict(valid=ok, records=n)
    return [step]


RUNNERS = dict(ml_model=ml_model, rules=rules, adds_up=adds_up, feedback=feedback, verify=verify, explain=explain)


def listing() -> list[dict]:
    return CHAPTERS


def run(desk, key: str) -> dict:
    return dict(BY_KEY[key], steps=RUNNERS[key](desk), clock=str(desk.now()))
