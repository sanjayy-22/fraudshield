"""Decision engine — cost-sensitive action selection.

Actions: ALLOW, STEP_UP (verify with the account owner: OTP / e-mail confirmation /
call-back / prepayment), HOLD (analyst review before pickup), BLOCK.

Instead of thresholding the fraud probability, pick the action with the lowest
*expected cost* for THIS booking, given

    p          calibrated fraud probability
    L          loss if a fraudulent booking is allowed = charge × (1 + ops_factor)
    C_block    cost of blocking a legitimate booking = lost charge + churn × LTV
    C_stepup   friction cost of asking a legitimate customer to verify
    C_hold     analyst cost + delay cost for a legitimate customer
    q_f, q_l   probability a fraudster / a legitimate customer passes step-up
    catch      probability an analyst catches fraud on review

    E[ALLOW]   = p·L
    E[BLOCK]   = (1-p)·C_block
    E[STEP_UP] = p·q_f·L + (1-p)·[C_stepup + (1-q_l)·C_block]
    E[HOLD]    = C_analyst + (1-p)·C_delay + p·(1-catch)·L        (only if capacity)

The same p therefore leads to BLOCK for a ₹300 parcel from a one-off individual and
to STEP_UP for a ₹300 parcel from an e-commerce account worth ₹3 lakh a year — which
is exactly the "false-positive control" the problem statement asks for, expressed in
rupees instead of adjectives. Hard rules override. Analyst capacity is a budget, and
(when a conformal prediction set is supplied) HOLD is reserved for bookings the model
itself declares ambiguous.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from collections import defaultdict

import numpy as np

POLICY_VERSION = "policy-2026.09.1"
ACTIONS = ["ALLOW", "STEP_UP", "HOLD", "BLOCK"]


@dataclass
class CostParams:
    ops_factor: float = 0.6         # operational cost of moving a parcel, as a share of the charge
    churn_if_blocked: float = 0.05  # P(customer churns | legitimate booking blocked)
    stepup_friction: float = 0.0005 # friction cost of a step-up for a legit customer, as share of LTV
    stepup_abandon: float = 0.02    # P(legit customer abandons the booking at step-up)
    hold_delay: float = 0.001       # delay cost for a legit customer, as share of LTV
    analyst_cost: float = 200.0     # INR per review
    legit_pass: float = 0.97        # P(legit passes step-up)
    fraud_pass: float = 0.20        # P(fraudster passes step-up)
    analyst_catch: float = 0.95     # P(analyst catches fraud on review)


@dataclass
class Decision:
    action: str
    expected_costs: dict
    reason: str
    policy: str = POLICY_VERSION


class ReviewCapacity:
    """Analyst review budget: `per_window` reviews per `window_hours`."""

    def __init__(self, per_window: int = 2, window_hours: int = 4):
        self.per_window, self.window_hours = per_window, window_hours
        self.used = defaultdict(int)

    def _key(self, ts):
        return (ts.date(), int(ts.hour) // self.window_hours)

    def available(self, ts) -> bool:
        return self.used[self._key(ts)] < self.per_window

    def consume(self, ts):
        self.used[self._key(ts)] += 1


def unit_costs(charge: float, ltv: float, cp: CostParams) -> dict:
    return dict(
        L=charge * (1 + cp.ops_factor),
        C_block=charge + cp.churn_if_blocked * ltv,
        C_stepup=cp.stepup_friction * ltv + cp.stepup_abandon * charge,
        C_delay=cp.hold_delay * ltv,
    )


def expected_costs(p: float, charge: float, ltv: float, cp: CostParams, hold_available: bool) -> dict:
    u = unit_costs(charge, ltv, cp)
    e = {
        "ALLOW": p * u["L"],
        "BLOCK": (1 - p) * u["C_block"],
        "STEP_UP": p * cp.fraud_pass * u["L"] + (1 - p) * (u["C_stepup"] + (1 - cp.legit_pass) * u["C_block"]),
        "HOLD": (cp.analyst_cost + (1 - p) * u["C_delay"] + p * (1 - cp.analyst_catch) * u["L"]) if hold_available else None,
    }
    return {k: (round(v, 2) if v is not None else None) for k, v in e.items()}


def cheapest(e: dict) -> str:
    return min((k for k in e if e[k] is not None), key=e.get)


# ----------------------------------------------------------------- policies
def cost_sensitive(p: float, charge: float, ltv: float, cp: CostParams, capacity: ReviewCapacity | None,
                   ts, hard_block: bool = False, conformal: dict | None = None) -> Decision:
    if hard_block:
        return Decision("BLOCK", {}, "hard rule")
    hold_ok = capacity is not None and capacity.available(ts)
    if conformal is not None:                 # spend analysts only where the model is uncertain
        hold_ok = hold_ok and conformal.get("ambiguous", False)
    e = expected_costs(p, charge, ltv, cp, hold_ok)
    action = cheapest(e)
    if action == "HOLD":
        capacity.consume(ts)
    return Decision(action, e, "min expected cost")


def fixed_threshold(p: float, thr: float, hard_block: bool = False) -> Decision:
    if hard_block or p >= thr:
        return Decision("BLOCK", {}, f"p ≥ {thr:.3f}" if not hard_block else "hard rule", "fixed-threshold")
    return Decision("ALLOW", {}, f"p < {thr:.3f}", "fixed-threshold")


def banded(p: float, t_low: float, t_high: float, capacity: ReviewCapacity | None, ts, hard_block: bool = False) -> Decision:
    if hard_block or p >= t_high:
        return Decision("BLOCK", {}, "p ≥ high threshold", "two-threshold")
    if p >= t_low:
        if capacity is not None and capacity.available(ts):
            capacity.consume(ts)
            return Decision("HOLD", {}, "grey band, reviewed", "two-threshold")
        return Decision("BLOCK", {}, "grey band, no review capacity", "two-threshold")
    return Decision("ALLOW", {}, "p < low threshold", "two-threshold")


# ----------------------------------------------------------------- outcome simulation (for evaluation only)
def realized_cost(action: str, is_fraud: bool, charge: float, ltv: float, cp: CostParams, rng: np.random.Generator) -> tuple[float, str]:
    """What the decision actually cost, given the true label. Returns (cost, outcome)."""
    u = unit_costs(charge, ltv, cp)
    if action == "ALLOW":
        return (u["L"], "fraud_shipped") if is_fraud else (0.0, "legit_ok")
    if action == "BLOCK":
        return (0.0, "fraud_stopped") if is_fraud else (u["C_block"], "legit_blocked")
    if action == "STEP_UP":
        if is_fraud:
            return (u["L"], "fraud_passed_stepup") if rng.random() < cp.fraud_pass else (0.0, "fraud_stopped")
        return (u["C_stepup"], "legit_verified") if rng.random() < cp.legit_pass else (u["C_block"], "legit_failed_stepup")
    if action == "HOLD":
        if is_fraud:
            return (cp.analyst_cost, "fraud_stopped") if rng.random() < cp.analyst_catch else (cp.analyst_cost + u["L"], "fraud_missed_review")
        return (cp.analyst_cost + u["C_delay"], "legit_reviewed")
    raise ValueError(action)
