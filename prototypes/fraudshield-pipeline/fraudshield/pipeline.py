"""FraudShield orchestrator: the synchronous scoring path + offline training + feedback.

Synchronous path per booking (target < 100 ms p99 in production; single-digit ms here):
    features (point-in-time store) → rules → calibrated GBM → conformal set
    → cost-sensitive decision → ledger append
Explanation is generated on demand / asynchronously via `explain()`.
"""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
from featurize import OnlineFeatureStore, build_feature_frame, FEATURE_COLS  # noqa: E402

from .conformal import MondrianConformal
from .decision import CostParams, ReviewCapacity, cost_sensitive
from .explain import explain as _explain
from .ledger import AuditLedger
from .model import RiskModel
from .rules import evaluate

FEATURE_VERSION = "features-2026.09.1"


class FraudShield:
    def __init__(self, cost_params: CostParams | None = None, review_capacity: ReviewCapacity | None = None,
                 ledger_path: str | Path | None = None, alpha: float = 0.10):
        self.store = OnlineFeatureStore()
        self.model: RiskModel | None = None
        self.conformal: MondrianConformal | None = None
        self.cp = cost_params or CostParams()
        self.capacity = review_capacity or ReviewCapacity()
        self.ledger = AuditLedger(ledger_path) if ledger_path else None
        self.alpha = alpha
        self.thresholds: dict[str, float] = {}

    # ------------------------------------------------------------------ offline
    def fit(self, history: pd.DataFrame) -> "FraudShield":
        """Replay labelled history through the online store (point-in-time features, delayed
        labels), train on the first 70 %, calibrate probabilities on the next 15 %, fit the
        conformal calibrator and baseline thresholds on the last 15 %. The store is left in
        its end-of-history state, ready for the live stream."""
        X = build_feature_frame(history, store=self.store)
        q70, q85 = X.ts.quantile(0.70), X.ts.quantile(0.85)
        tr, cal_a, cal_b = X[X.ts < q70], X[(X.ts >= q70) & (X.ts < q85)], X[X.ts >= q85]
        self.model = RiskModel(FEATURE_COLS).fit(tr, tr.is_fraud.values).calibrate(cal_a, cal_a.is_fraud.values)
        p_b = self.model.predict_proba(cal_b)
        y_b = cal_b.is_fraud.values
        self.conformal = MondrianConformal().fit(p_b, y_b)
        neg = np.sort(p_b[y_b == 0])[::-1]
        self.thresholds = {k: float(neg[min(int(f * len(neg)), len(neg) - 1)])
                           for k, f in [("fpr_0_5pct", 0.005), ("fpr_1pct", 0.01), ("fpr_2pct", 0.02)]}
        self.training_summary = dict(train=len(tr), train_fraud=int(tr.is_fraud.sum()), calib=len(cal_a),
                                     conformal=len(cal_b), conformal_fraud=int(y_b.sum()),
                                     model_version=self.model.version)
        return self

    # ------------------------------------------------------------------ online
    def score(self, booking: dict) -> dict:
        t0 = perf_counter()
        f = self.store.features(booking)
        rr = evaluate(f)
        p = self.model.predict_one(f)
        conf = self.conformal.prediction_set(p, self.alpha)
        dec = cost_sensitive(p, booking["charge_inr"], booking["ltv"], self.cp, self.capacity,
                             booking["ts"], rr.hard_block, conf)
        latency_ms = (perf_counter() - t0) * 1000
        result = dict(
            booking_id=booking["booking_id"], shipper_id=booking["shipper_id"], cohort=booking["cohort"],
            ts=str(booking["ts"]), charge_inr=booking["charge_inr"], ltv=booking["ltv"],
            p_fraud=p, rules=asdict(rr), conformal=conf, decision=asdict(dec), latency_ms=round(latency_ms, 3),
            feature_version=FEATURE_VERSION, model_version=self.model.version,
            features={c: float(f[c]) for c in FEATURE_COLS + ["n_hist"]},
        )
        if self.ledger is not None:
            self.ledger.append(result)
        return result

    def explain(self, result: dict) -> dict:
        return _explain(result, self.model, self.thresholds["fpr_1pct"])

    def feedback(self, booking: dict, outcome: str):
        """Close the loop.
        confirmed_fraud  — step-up failed / analyst confirmed: fast label (1 day), profile quarantine
        verified_legit   — step-up passed / analyst cleared: absorb into profile normally
        not_shipped      — blocked, unverified: entities recorded, profile untouched, no label
        unknown          — shipped without verification: absorb; if it later turns out to be fraud the
                           post-delivery process delivers the label after the usual delay
        """
        if outcome == "confirmed_fraud":
            self.store.update(booking, is_fraud=True, absorb_profile=False, label_delay=1.0)
        elif outcome == "verified_legit":
            self.store.update(booking, is_fraud=False)
        elif outcome == "not_shipped":
            self.store.update(booking, is_fraud=False, absorb_profile=False)
        else:
            self.store.update(booking, is_fraud=bool(booking.get("is_fraud", False)))
