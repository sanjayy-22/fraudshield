"""Mondrian (class-conditional) split conformal prediction for a binary risk score.

Gives every decision a distribution-free uncertainty statement: at confidence
1-alpha, is the prediction set {legit}, {fraud} or {legit, fraud}? An *ambiguous*
set is the principled trigger for spending scarce analyst capacity: the model
itself is saying "I cannot tell", instead of a hand-picked grey band of scores.
"""
from __future__ import annotations

import numpy as np


class MondrianConformal:
    def __init__(self):
        self.s0 = np.array([])     # nonconformity of legitimate calibration bookings: p
        self.s1 = np.array([])     # nonconformity of fraud calibration bookings: 1 - p

    def fit(self, p_cal: np.ndarray, y_cal: np.ndarray) -> "MondrianConformal":
        p_cal, y_cal = np.asarray(p_cal), np.asarray(y_cal)
        self.s0 = np.sort(p_cal[y_cal == 0])
        self.s1 = np.sort(1 - p_cal[y_cal == 1])
        return self

    def p_values(self, p: float) -> tuple[float, float]:
        """(p-value that the booking is legit, p-value that it is fraud)."""
        pv0 = (np.sum(self.s0 >= p) + 1) / (len(self.s0) + 1)
        pv1 = (np.sum(self.s1 >= 1 - p) + 1) / (len(self.s1) + 1)
        return float(pv0), float(pv1)

    def prediction_set(self, p: float, alpha: float = 0.10) -> dict:
        pv0, pv1 = self.p_values(p)
        members = [lbl for lbl, pv in (("legit", pv0), ("fraud", pv1)) if pv > alpha]
        return dict(alpha=alpha, p_value_legit=round(pv0, 4), p_value_fraud=round(pv1, 4),
                    set=members, ambiguous=len(members) != 1)
