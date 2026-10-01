"""Deterministic, versioned rules engine.

Rules are the part of the system a fraud analyst can read, change and sign off on
without retraining anything. Each rule has a stable reason code (used in the audit
ledger and in explanations), a weight (its stand-alone fraud belief, combined by
noisy-OR) and a `hard` flag (hard rules force a BLOCK regardless of the model).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

RULESET_VERSION = "rules-2026.09.1"


@dataclass(frozen=True)
class Rule:
    code: str
    weight: float
    text: str
    predicate: Callable[[dict], bool]
    hard: bool = False


RULES: list[Rule] = [
    Rule("R01_NEW_PAY_NEW_DEST_EXPRESS", 0.60,
         "payment instrument added <60 min ago + never-seen destination + express/priority",
         lambda f: f["new_payment"] == 1 and f["log_pay_age_min"] < np.log1p(60) and f["dest_addr_seen"] == 0 and f["is_express"] == 1),
    Rule("R02_VELOCITY_SPIKE", 0.50, "≥5 bookings in the last hour and >8× the shipper's daily baseline",
         lambda f: f["vel_1h"] >= 5 and f["vel24_ratio"] > 8),
    Rule("R03_DORMANT_REACTIVATION", 0.50, "no bookings for ≥60 days, then a new destination from a new device",
         lambda f: f["days_since_last"] >= 60 and f["dest_addr_seen"] == 0 and f["new_device"] == 1),
    Rule("R04_KNOWN_MULE_DEST", 0.80, "destination address linked to ≥2 confirmed fraud shipments",
         lambda f: f["dest_fraud"] >= 2, hard=True),
    Rule("R05_SHARED_FRAUD_DEVICE", 0.70, "device previously used on confirmed-fraud bookings, new to this shipper",
         lambda f: f["dev_fraud"] >= 1 and f["new_device"] == 1),
    Rule("R06_WEIGHT_OUTLIER", 0.30, "weight >4σ above the shipper's own history",
         lambda f: f["w_z"] > 4),
    Rule("R07_OFFHOURS_NEW_DEVICE_NEW_DEST", 0.40, "booked 00:00–05:00 from a new device to a new destination",
         lambda f: f["hour"] < 5 and f["new_device"] == 1 and f["dest_addr_seen"] == 0),
    Rule("R08_CONFIRMED_FRAUD_PAYMENT", 0.90, "payment instrument already used on confirmed fraud",
         lambda f: f["pay_fraud"] >= 1, hard=True),
]
RULE_TEXT = {r.code: r.text for r in RULES}


@dataclass
class RuleResult:
    score: float
    hits: list[str]
    hard_block: bool
    version: str = RULESET_VERSION


def evaluate(features: dict) -> RuleResult:
    hits = [r for r in RULES if r.predicate(features)]
    score = 1.0 - float(np.prod([1 - r.weight for r in hits])) if hits else 0.0
    return RuleResult(score=score, hits=[r.code for r in hits], hard_block=any(r.hard for r in hits))
