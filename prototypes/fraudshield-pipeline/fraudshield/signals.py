"""Shipment signals for the 8 shipment rules (rules.py R01–R08) on the booking desk.

DataCo orders carry no device, payment-method age, parcel weight or street address, so the desk
collects them as optional "extra signals" and remembers them per customer. Customer history
(orders per hour/day, days since the last order, cities shipped to) comes from the same order
history the model uses (DataCoShield.known), so rules and model see one consistent past.

`SignalStore.compute()` returns exactly the feature names rules.py reads, so the rule code is the
same one the synthetic pipeline uses.

Feedback loop:
* confirmed fraud (analyst rejects, or 3 wrong codes) → the order's device, payment method and
  address go into the fraud registries (R04 / R05 / R08 fire next time);
* confirmed genuine (approved or verified) → they join the customer's normal profile.

Blank fields mean "nothing unusual": the customer's usual device, their usual (old) payment method,
no weight check, no street address.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from .rules import RULES

# Plain-language catalogue of every rule the desk can match: the 8 shipment rules from rules.py and
# the 3 DataCo data rules from dataco.py. Weights come from the rule definitions themselves.
PLAIN = {
    "R01_NEW_PAY_NEW_DEST_EXPRESS": ("New payment + new destination + express",
                                     "A payment method added less than an hour ago, sending to a place this customer never used, with fast delivery. Typical of a stolen card being used quickly."),
    "R02_VELOCITY_SPIKE": ("Booking burst",
                           "5 or more bookings in the last hour, and more than 8 times the customer's normal daily amount. Typical of a hijacked account being emptied fast."),
    "R03_DORMANT_REACTIVATION": ("Sleeping account wakes up",
                                 "No orders for 60+ days, then an order from a new device to a new destination. Typical of a taken-over old account."),
    "R04_KNOWN_MULE_DEST": ("Known fraud address",
                            "This delivery address already received 2 or more confirmed fraud parcels. Always stopped."),
    "R05_SHARED_FRAUD_DEVICE": ("Device linked to fraud",
                                "The phone or computer was used in confirmed fraud before and is new to this customer."),
    "R06_WEIGHT_OUTLIER": ("Unusually heavy parcel",
                           "The parcel is far heavier than this customer usually sends (more than 4 standard deviations)."),
    "R07_OFFHOURS_NEW_DEVICE_NEW_DEST": ("Night order, new device, new destination",
                                         "Booked between midnight and 5 a.m. from a new device to a new destination."),
    "R08_CONFIRMED_FRAUD_PAYMENT": ("Payment method linked to fraud",
                                    "This card or account was used in confirmed fraud before. Always stopped."),
    "D01_TRANSFER": ("Bank transfer",
                     "Paid by bank transfer. In the DataCo data every fraud case was a bank transfer."),
    "D02_PRIOR_FRAUD_CUSTOMER": ("Customer flagged before",
                                 "This customer had an earlier order flagged as suspected fraud."),
    "D03_HIGH_DISCOUNT_NEW_CUSTOMER": ("Big discount on a first order",
                                       "A first-time customer using a discount of 20% or more."),
}

EXPRESS = {"Same Day", "First Class"}
UNKNOWN_AGE_MIN = 1e5            # "old" payment method when nobody told us its age


def addr_key(address: str, city: str) -> str:
    return f"{' '.join(address.lower().split())}|{city.lower().strip()}"


class SignalStore:
    def __init__(self):
        self.devices: dict[int, set] = defaultdict(set)
        self.payments: dict[int, dict] = defaultdict(dict)       # customer → {method: added_at}
        self.addresses: dict[int, set] = defaultdict(set)
        self.weights: dict[int, list] = defaultdict(list)
        self.device_fraud: Counter = Counter()
        self.payment_fraud: Counter = Counter()
        self.address_fraud: Counter = Counter()

    # ------------------------------------------------------------------ features for rules.py
    def compute(self, known: pd.DataFrame, order: dict, sig: dict, ts: pd.Timestamp) -> tuple[dict, dict]:
        """Returns (features for rules.py, readable facts for the UI)."""
        cid = order["customer_id"]
        hist = known[(known.customer_id == cid) & (known.ts < ts)]
        vel_1h = int((hist.ts >= ts - pd.Timedelta(hours=1)).sum())
        vel_24h = int((hist.ts >= ts - pd.Timedelta(hours=24)).sum())
        base = hist[(hist.ts < ts - pd.Timedelta(hours=24)) & (hist.ts >= ts - pd.Timedelta(days=90))]
        rate = len(base) / 90.0
        vel24_ratio = vel_24h / max(rate, 0.02)
        days_since_last = float((ts - hist.ts.max()).total_seconds() / 86400) if len(hist) else 0.0

        device = (sig.get("device_id") or "").strip()
        new_device = int(bool(device) and device not in self.devices[cid])
        pay = (sig.get("payment_id") or "").strip()
        new_payment = int(bool(pay) and pay not in self.payments[cid])
        age = sig.get("payment_added_minutes_ago")
        if age in (None, ""):
            added = self.payments[cid].get(pay) if pay else None
            age = (ts - added).total_seconds() / 60 if added is not None else UNKNOWN_AGE_MIN
        age = max(float(age), 0.0)
        address = (sig.get("address") or "").strip()
        akey = addr_key(address, order["order_city"]) if address else None
        city_seen = bool((hist.order_city == order["order_city"]).any())
        dest_seen = int(city_seen and (akey is None or akey in self.addresses[cid]))

        w = sig.get("weight_kg")
        past_w = self.weights[cid][-20:]
        w_z = 0.0
        if w not in (None, "") and len(past_w) >= 3:
            mean = float(np.mean(past_w))
            std = max(float(np.std(past_w)), 0.1 * mean, 0.05)
            w_z = (float(w) - mean) / std

        f = dict(
            new_payment=new_payment, log_pay_age_min=math.log1p(age), dest_addr_seen=dest_seen,
            is_express=int(order["shipping_mode"] in EXPRESS), vel_1h=vel_1h, vel24_ratio=vel24_ratio,
            days_since_last=days_since_last, new_device=new_device,
            dest_fraud=self.address_fraud[akey] if akey else 0,
            dev_fraud=self.device_fraud[device] if device else 0,
            pay_fraud=self.payment_fraud[pay] if pay else 0, w_z=w_z, hour=int(ts.hour),
        )
        facts = dict(
            bookings_last_hour=vel_1h, bookings_last_24h=vel_24h, usual_bookings_per_day=round(rate, 3),
            times_normal_daily=round(vel24_ratio, 1), days_since_last_order=round(days_since_last, 1) if len(hist) else None,
            device=device or "usual device", new_device=bool(new_device),
            payment_method=pay or "usual payment method", new_payment_method=bool(new_payment),
            payment_age_minutes=None if age >= UNKNOWN_AGE_MIN else round(age),
            destination_seen_before=bool(dest_seen), express=bool(f["is_express"]), booking_hour=int(ts.hour),
            parcel_weight_kg=None if w in (None, "") else float(w),
            usual_weight_kg=round(float(np.mean(past_w)), 2) if past_w else None,
            weight_vs_usual_sd=round(w_z, 1) if past_w and w not in (None, "") else None,
            fraud_cases_at_address=f["dest_fraud"], fraud_cases_on_device=f["dev_fraud"],
            fraud_cases_on_payment=f["pay_fraud"],
        )
        return f, facts

    # ------------------------------------------------------------------ feedback
    def record_genuine(self, cid: int, order: dict, sig: dict, ts: pd.Timestamp) -> None:
        if sig.get("device_id"):
            self.devices[cid].add(sig["device_id"].strip())
        if sig.get("payment_id"):
            age = sig.get("payment_added_minutes_ago")
            added = ts - pd.Timedelta(minutes=float(age)) if age not in (None, "") else ts - pd.Timedelta(days=365)
            self.payments[cid].setdefault(sig["payment_id"].strip(), added)
        if sig.get("address"):
            self.addresses[cid].add(addr_key(sig["address"], order["order_city"]))
        if sig.get("weight_kg") not in (None, ""):
            self.weights[cid].append(float(sig["weight_kg"]))

    def record_fraud(self, order: dict, sig: dict) -> list[str]:
        added = []
        if sig.get("device_id"):
            self.device_fraud[sig["device_id"].strip()] += 1
            added.append(f"device {sig['device_id'].strip()}")
        if sig.get("payment_id"):
            self.payment_fraud[sig["payment_id"].strip()] += 1
            added.append(f"payment method {sig['payment_id'].strip()}")
        if sig.get("address"):
            self.address_fraud[addr_key(sig["address"], order["order_city"])] += 1
            added.append(f"address {sig['address'].strip()}, {order['order_city']}")
        return added


def shipment_rule_hits(features: dict) -> list:
    """The rules.py rules that match (same objects the synthetic pipeline uses)."""
    return [r for r in RULES if r.predicate(features)]


def catalogue(extra_rules: list) -> list[dict]:
    """Every rule the desk knows, for the rules guide."""
    out = [dict(code=r.code, name=PLAIN[r.code][0], plain=PLAIN[r.code][1], weight=r.weight, hard=r.hard, group="shipment")
           for r in RULES]
    out += [dict(code=r.code, name=PLAIN[r.code][0], plain=PLAIN[r.code][1], weight=r.weight, hard=r.hard, group="data")
            for r in extra_rules]
    return out
