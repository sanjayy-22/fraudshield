"""Risk model: gradient-boosted classifier + probability calibration + attributions.

The model sees behavioural, velocity, identity, entity-graph and drift features (the
detectors of experiments A, B and C fused at feature level — a stacked model rather
than three separately-thresholded scores). Calibration (isotonic, on a time-ordered
hold-out slice) matters because the decision engine consumes p as a *probability* in
an expected-cost computation, not as a ranking score.
"""
from __future__ import annotations

import hashlib
import pickle

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

MODEL_FAMILY = "lightgbm"
try:
    import lightgbm as lgb
except ImportError:      # pragma: no cover
    lgb = None
    MODEL_FAMILY = "sklearn-hgb"


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


class RiskModel:
    def __init__(self, feature_cols: list[str]):
        self.feature_cols = list(feature_cols)
        self.model = None
        self.calibrator: LogisticRegression | None = None
        self.version = "untrained"

    # ------------------------------------------------------------------ training
    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "RiskModel":
        if lgb is not None:
            self.model = lgb.LGBMClassifier(
                n_estimators=400, learning_rate=0.04, num_leaves=31, min_child_samples=25,
                subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=2.0,
                scale_pos_weight=5.0, verbose=-1, random_state=1)
        else:
            from sklearn.ensemble import HistGradientBoostingClassifier
            self.model = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05,
                                                        class_weight="balanced", random_state=1)
        self.model.fit(X[self.feature_cols].astype(float), y)
        digest = hashlib.sha256(pickle.dumps(self.model)).hexdigest()[:12]
        self.version = f"{MODEL_FAMILY}-{digest}"
        return self

    def calibrate(self, X_cal: pd.DataFrame, y_cal: np.ndarray) -> "RiskModel":
        """Platt scaling on the raw log-odds (a monotone sigmoid re-map). Chosen over isotonic
        regression because with a few dozen fraud cases in the calibration slice isotonic
        collapses into plateaus at 0/1, which destroys the ranking inside each plateau and
        makes threshold policies degenerate."""
        z = _logit(self._raw(X_cal))
        self.calibrator = LogisticRegression(C=1e6, max_iter=1000).fit(z.reshape(-1, 1), y_cal)
        return self

    # ------------------------------------------------------------------ inference
    def _raw(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(X[self.feature_cols].astype(float))[:, 1]

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        raw = self._raw(X)
        if self.calibrator is None:
            return raw
        return self.calibrator.predict_proba(_logit(raw).reshape(-1, 1))[:, 1]

    def predict_one(self, features: dict) -> float:
        row = pd.DataFrame([{c: features[c] for c in self.feature_cols}])
        return float(self.predict_proba(row)[0])

    def contributions(self, features: dict) -> pd.Series:
        """Per-feature contribution to the raw log-odds (exact TreeSHAP via LightGBM's
        pred_contrib; leave-one-out fallback otherwise)."""
        row = pd.DataFrame([{c: features[c] for c in self.feature_cols}]).astype(float)
        if lgb is not None and isinstance(self.model, lgb.LGBMClassifier):
            c = self.model.booster_.predict(row, pred_contrib=True)[0][:-1]
            return pd.Series(c, index=self.feature_cols)
        base = self.model.predict_proba(row)[0, 1]
        out = {}
        for f in self.feature_cols:
            r2 = row.copy(); r2[f] = 0.0
            out[f] = base - self.model.predict_proba(r2)[0, 1]
        return pd.Series(out)
