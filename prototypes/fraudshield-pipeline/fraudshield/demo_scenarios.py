"""Demo scenarios: one per shipment rule, plus combinations, for a clean live demo.

Each scenario creates a fresh demo customer (IDs from 900001) and seeds only the history that
scenario needs (earlier orders, usual device, usual parcel weights, confirmed-fraud registries),
timed relative to the planned booking time. It returns the order form to submit and a list of
"what we set up" notes the UI shows, so nothing is hidden from the audience.

All scenarios pay by card (DEBIT): on card orders the AI model's own fraud score is about 0.1%, so
the rules alone explain the outcome. Every scenario fixes a booking time (11:00, or 02:00 for the
night rule) so the result does not depend on when the demo is run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

DEMO_CUSTOMER_START = 900001
HOME = dict(customer_segment="Consumer", customer_country="EE. UU.", customer_city="Chicago")
USUAL = dict(order_country="Estados Unidos", order_city="Chicago")
ITEMS = [dict(product_id=365, quantity=2, discount_rate=0.0)]          # 2 × Perfect Fitness Rip Deck, $119.98


@dataclass
class Scenario:
    key: str
    title: str
    group: str            # "one" (single rule) or "combo"
    rules: list
    expect: str           # CONFIRMED / VERIFICATION_REQUIRED / UNDER_REVIEW / BLOCKED
    summary: str
    build: Callable


# ------------------------------------------------------------------ helpers
def _plan(desk, hour: int) -> pd.Timestamp:
    """Next time the demo clock shows hour:00 (at least 2 minutes ahead)."""
    now = desk.now()
    t = now.normalize() + pd.Timedelta(hours=hour)
    if t <= now + pd.Timedelta(minutes=2):
        t += pd.Timedelta(days=1)
    return t


def _customer(desk, at: pd.Timestamp, history: list[tuple[pd.Timedelta, str, str]], devices=(), weights=()) -> int:
    """New demo customer with earlier orders (offset before `at`, country, city)."""
    cid = max(DEMO_CUSTOMER_START, getattr(desk, "_next_demo_customer", DEMO_CUSTOMER_START))
    desk._next_demo_customer = cid + 1
    desk.customers.loc[cid] = [HOME["customer_segment"], HOME["customer_country"], HOME["customer_city"]]
    rows = []
    for back, country, city in history:
        rows.append(dict(order_id=desk.next_order_id, customer_id=cid, ts=at - back, net_total=119.98, is_transfer=0,
                         is_fraud=0, is_cancel=0, order_country=country, order_city=city))
        desk.next_order_id += 1
    if rows:
        new = pd.DataFrame(rows)
        new["ts"] = new.ts.astype("datetime64[ns]")
        desk.shield.known = pd.concat([desk.shield.known, new], ignore_index=True)
    desk.customer_orders.loc[cid] = len(rows)
    for d in devices:
        desk.signals.devices[cid].add(d)
    desk.signals.weights[cid].extend(weights)
    return cid


def _form(cid, at, **kw) -> dict:
    sig = kw.pop("signals", {})
    form = dict(customer_id=cid, payment_type="DEBIT", shipping_mode="Standard Class", items=ITEMS,
                book_at=str(at), signals=sig, **USUAL)
    form.update(kw)
    return form


def _days(n):
    return pd.Timedelta(days=n)


def _regular(at):
    """Four ordinary orders to Chicago over the last two months."""
    return [(_days(d), USUAL["order_country"], USUAL["order_city"]) for d in (58, 41, 27, 12)]


# ------------------------------------------------------------------ scenarios
def heavy(desk):
    at = _plan(desk, 11)
    cid = _customer(desk, at, _regular(at), devices=["PHONE-HOME"], weights=[1.0, 1.2, 0.9, 1.1, 1.0])
    return _form(cid, at, signals=dict(weight_kg=14)), [
        f"Customer {cid} usually sends parcels of about 1 kg (last 5: 1.0, 1.2, 0.9, 1.1, 1.0 kg).",
        "This parcel weighs 14 kg."]


def night(desk):
    at = _plan(desk, 2)
    cid = _customer(desk, at, _regular(at), devices=["PHONE-HOME"])
    return _form(cid, at, order_city="Los Angeles", signals=dict(device_id="LAPTOP-UNKNOWN-7")), [
        f"Customer {cid} always used PHONE-HOME and always shipped to Chicago.",
        "This order is booked at 02:00 from a new device (LAPTOP-UNKNOWN-7) to Los Angeles."]


def burst(desk):
    at = _plan(desk, 11)
    hist = [(_days(70), "Estados Unidos", "Chicago"), (_days(35), "Estados Unidos", "Chicago")]
    hist += [(pd.Timedelta(minutes=m), "Estados Unidos", "Chicago") for m in (52, 41, 30, 19, 8)]
    cid = _customer(desk, at, hist, devices=["PHONE-HOME"])
    return _form(cid, at), [
        f"Customer {cid} normally orders about once a month (2 orders in the last 90 days).",
        "We added 5 bookings in the 52 minutes before this one."]


def dormant(desk):
    at = _plan(desk, 11)
    hist = [(_days(d), "Estados Unidos", "Chicago") for d in (240, 180, 120, 95)]
    cid = _customer(desk, at, hist, devices=["PHONE-HOME"])
    return _form(cid, at, order_city="Houston", signals=dict(device_id="TABLET-NEW-3")), [
        f"Customer {cid}'s last order was 95 days ago, always to Chicago from PHONE-HOME.",
        "Now: a new device (TABLET-NEW-3) shipping to Houston."]


def new_card(desk):
    at = _plan(desk, 11)
    cid = _customer(desk, at, _regular(at), devices=["PHONE-HOME"])
    return _form(cid, at, order_city="Seattle", shipping_mode="Same Day",
                 signals=dict(payment_id="CARD-NEW-4411", payment_added_minutes_ago=20)), [
        f"Customer {cid} always paid with their usual card and shipped to Chicago.",
        "A new card (CARD-NEW-4411) was added 20 minutes ago; same-day delivery to Seattle."]


def bad_device(desk):
    at = _plan(desk, 11)
    cid = _customer(desk, at, _regular(at), devices=["PHONE-HOME"])
    desk.signals.device_fraud["PHONE-RING-01"] = max(desk.signals.device_fraud["PHONE-RING-01"], 1)
    return _form(cid, at, signals=dict(device_id="PHONE-RING-01")), [
        "Device PHONE-RING-01 was used in 1 confirmed fraud case by another account.",
        f"Customer {cid} has never used it before."]


def mule_address(desk):
    at = _plan(desk, 11)
    cid = _customer(desk, at, _regular(at), devices=["PHONE-HOME"])
    from .signals import addr_key
    key = addr_key("Calle 8 #45, Bodega 3", "Mexico City")
    desk.signals.address_fraud[key] = max(desk.signals.address_fraud[key], 2)
    return _form(cid, at, order_country="México", order_city="Mexico City",
                 signals=dict(address="Calle 8 #45, Bodega 3")), [
        "Address 'Calle 8 #45, Bodega 3, Mexico City' already received 2 confirmed fraud parcels.",
        f"Customer {cid} is sending a parcel there."]


def fraud_card(desk):
    at = _plan(desk, 11)
    cid = _customer(desk, at, _regular(at), devices=["PHONE-HOME"])
    desk.signals.payment_fraud["CARD-STOLEN-0077"] = max(desk.signals.payment_fraud["CARD-STOLEN-0077"], 1)
    return _form(cid, at, signals=dict(payment_id="CARD-STOLEN-0077", payment_added_minutes_ago=4320)), [
        "Card CARD-STOLEN-0077 was used in 1 confirmed fraud case.",
        f"Customer {cid} added it 3 days ago and pays with it now."]


def burst_heavy(desk):
    at = _plan(desk, 11)
    hist = [(_days(70), "Estados Unidos", "Chicago"), (_days(35), "Estados Unidos", "Chicago")]
    hist += [(pd.Timedelta(minutes=m), "Estados Unidos", "Chicago") for m in (55, 44, 33, 22, 11)]
    cid = _customer(desk, at, hist, devices=["PHONE-HOME"], weights=[1.0, 1.2, 0.9, 1.1, 1.0])
    return _form(cid, at, signals=dict(weight_kg=14)), [
        f"Customer {cid}: 5 bookings in the last hour, after only 2 in the last 90 days.",
        "Usual parcels weigh about 1 kg; this one weighs 14 kg."]


def dormant_night(desk):
    at = _plan(desk, 2)
    hist = [(_days(d), "Estados Unidos", "Chicago") for d in (240, 180, 120, 95)]
    cid = _customer(desk, at, hist, devices=["PHONE-HOME"])
    return _form(cid, at, order_city="Houston", signals=dict(device_id="TABLET-NEW-3")), [
        f"Customer {cid}'s last order was 95 days ago.",
        "Now: booked at 02:00 from a new device (TABLET-NEW-3) to Houston."]


def card_device_night(desk):
    at = _plan(desk, 2)
    cid = _customer(desk, at, _regular(at), devices=["PHONE-HOME"])
    desk.signals.device_fraud["PHONE-RING-02"] = max(desk.signals.device_fraud["PHONE-RING-02"], 1)
    return _form(cid, at, order_city="Seattle", shipping_mode="Same Day",
                 signals=dict(device_id="PHONE-RING-02", payment_id="CARD-NEW-9020", payment_added_minutes_ago=15)), [
        "Device PHONE-RING-02 was used in 1 confirmed fraud case by another account.",
        f"Customer {cid}: a new card added 15 minutes ago, booked at 02:00, same-day delivery to Seattle."]


SCENARIOS = [
    Scenario("heavy", "Unusually heavy parcel", "one", ["R06_WEIGHT_OUTLIER"], "VERIFICATION_REQUIRED",
             "14 kg when the customer usually sends 1 kg", heavy),
    Scenario("night", "Night order, new device", "one", ["R07_OFFHOURS_NEW_DEVICE_NEW_DEST"], "VERIFICATION_REQUIRED",
             "02:00, unknown laptop, new city", night),
    Scenario("burst", "Booking burst", "one", ["R02_VELOCITY_SPIKE"], "VERIFICATION_REQUIRED",
             "6th booking in one hour", burst),
    Scenario("dormant", "Sleeping account wakes up", "one", ["R03_DORMANT_REACTIVATION"], "VERIFICATION_REQUIRED",
             "95 days quiet, new device, new city", dormant),
    Scenario("new_card", "New card, new place, express", "one", ["R01_NEW_PAY_NEW_DEST_EXPRESS"], "UNDER_REVIEW",
             "card added 20 min ago, same-day to a new city", new_card),
    Scenario("bad_device", "Device linked to fraud", "one", ["R05_SHARED_FRAUD_DEVICE"], "UNDER_REVIEW",
             "phone used in a confirmed fraud case", bad_device),
    Scenario("mule_address", "Known fraud address", "one", ["R04_KNOWN_MULE_DEST"], "BLOCKED",
             "address with 2 confirmed fraud parcels", mule_address),
    Scenario("fraud_card", "Card linked to fraud", "one", ["R08_CONFIRMED_FRAUD_PAYMENT"], "BLOCKED",
             "card used in a confirmed fraud case", fraud_card),
    Scenario("burst_heavy", "Burst + heavy parcel", "combo", ["R02_VELOCITY_SPIKE", "R06_WEIGHT_OUTLIER"], "UNDER_REVIEW",
             "two medium signals add up to review", burst_heavy),
    Scenario("dormant_night", "Sleeping account at night", "combo",
             ["R03_DORMANT_REACTIVATION", "R07_OFFHOURS_NEW_DEVICE_NEW_DEST"], "UNDER_REVIEW",
             "two signals from one takeover", dormant_night),
    Scenario("card_device_night", "New card + fraud device + night", "combo",
             ["R05_SHARED_FRAUD_DEVICE", "R01_NEW_PAY_NEW_DEST_EXPRESS", "R07_OFFHOURS_NEW_DEVICE_NEW_DEST"], "BLOCKED",
             "three signals pass the 85% stop line", card_device_night),
]
BY_KEY = {s.key: s for s in SCENARIOS}


def listing() -> list[dict]:
    return [dict(key=s.key, title=s.title, group=s.group, rules=s.rules, expect=s.expect, summary=s.summary)
            for s in SCENARIOS]


def prepare(desk, key: str) -> dict:
    s = BY_KEY[key]
    form, notes = s.build(desk)
    return dict(key=key, title=s.title, rules=s.rules, expect=s.expect, form=form, notes=notes)
