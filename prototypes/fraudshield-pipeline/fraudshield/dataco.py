"""DataCoShield: the FraudShield live path on real DataCo orders.

Same components as `pipeline.FraudShield` (calibrated GBM → Mondrian conformal → cost-sensitive
decision → hash-chained ledger), wired to the DataCo booking-time feature contract in
prototypes/data/dataco_features.py instead of the synthetic feature store.

Used by demo_dataco.py (batch replay) and api_dataco.py (one order at a time).

Assumptions, because DataCo does not record them: money is the order total in USD;
LTV = max(2 × prior spend, order value); an analyst review costs 5 USD.
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import dataco_features as F  # noqa: E402

from .conformal import MondrianConformal
from .decision import CostParams, ReviewCapacity, cost_sensitive
from .ledger import AuditLedger
from .model import RiskModel
from .rules import Rule, RuleResult

FEATURE_VERSION = "dataco-features-2026.10.1"
RULESET_VERSION = "dataco-rules-2026.10.1"
COLS = F.honest_features(include_payment=True)
DATACO_COST = CostParams(analyst_cost=5.0)          # USD; every other parameter is a share of charge / LTV

# Informational rules. None is hard: the E3 audit found prior fraud on the customer does not raise
# the next order's fraud rate (0.075 vs 0.083), so a hard block would only add false positives.
DATACO_RULES = [
    Rule("D01_TRANSFER", 0.08, "bank-transfer payment (the only payment type with fraud in DataCo)",
         lambda f: f["is_transfer"] == 1),
    Rule("D02_PRIOR_FRAUD_CUSTOMER", 0.08, "customer had an earlier order flagged SUSPECTED_FRAUD",
         lambda f: f["cust_prior_fraud"] >= 1),
    Rule("D03_HIGH_DISCOUNT_NEW_CUSTOMER", 0.05, "first order with discount rate ≥ 20 %",
         lambda f: f["cust_n_prior"] == 0 and f["discount_rate_max"] >= 0.2),
]
RULE_TEXT = {r.code: r.text for r in DATACO_RULES}

# plain-language labels for explanations
LABELS = {
    "is_transfer": "paid by bank transfer", "discount_rate_mean": "average discount rate",
    "discount_rate_max": "highest discount rate", "discount_total": "discount amount (USD)",
    "net_total": "order value (USD)", "gross_sales": "order value before discount (USD)",
    "profit_total": "order profit (USD)", "profit_ratio_mean": "profit ratio", "order_hour": "hour of order",
    "order_day": "day of month", "order_weekday": "weekday (0 = Monday)", "n_units": "units ordered",
    "n_items": "order lines", "cust_prior_spend": "customer's earlier spend (USD)",
    "cust_days_since_last": "days since customer's last order", "cust_n_prior": "customer's earlier orders",
    "cust_spend_ratio": "order value vs customer's average", "cust_prior_fraud": "customer's earlier fraud flags",
    "order_region": "destination region", "main_category": "main product category", "market": "market",
    "main_department": "main department", "shipping_mode": "shipping mode", "customer_segment": "customer segment",
    "customer_country": "customer country", "days_shipment_scheduled": "scheduled shipping days",
    "n_categories": "product categories in the order", "n_departments": "departments in the order",
    "max_unit_price": "highest unit price (USD)", "cust_orders_7d": "customer's orders in the last 7 days",
    "cust_orders_30d": "customer's orders in the last 30 days", "cust_prior_transfer": "customer's earlier bank transfers",
    "cust_prior_cancel": "customer's earlier cancelled orders", "cust_new_country": "first order to this country",
    "cust_new_city": "first order to this city",
}


def evaluate_rules(f: dict) -> RuleResult:
    hits = [r for r in DATACO_RULES if r.predicate(f)]
    score = 1.0 - float(np.prod([1 - r.weight for r in hits])) if hits else 0.0
    return RuleResult(score=score, hits=[r.code for r in hits], hard_block=False, version=RULESET_VERSION)


def charge_and_ltv(order: dict) -> tuple[float, float]:
    charge = float(order["net_total"])
    return charge, max(2.0 * float(order["cust_prior_spend"]), charge)


class CategoryCoder:
    """Freeze category → integer codes on the training split (unseen values → -1), so a ledger record's
    plain float vector is enough to replay the decision."""

    def __init__(self, train: pd.DataFrame):
        self.maps = {c: {v: i for i, v in enumerate(sorted(train[c].astype(str).unique()))} for c in F.CAT_COLS}
        self.names = {c: {i: v for v, i in m.items()} for c, m in self.maps.items()}

    def decode(self, col: str, value: float):
        """Human-readable value of a feature (category name for coded categoricals)."""
        if col in self.names:
            return self.names[col].get(int(value), "unseen")
        return value

    def transform(self, d: pd.DataFrame) -> pd.DataFrame:
        X = d[COLS].copy()
        for c in F.CAT_COLS:
            X[c] = X[c].astype(str).map(self.maps[c]).fillna(-1).astype(float)
        return X.astype(float)


class DataCoShield:
    def __init__(self, ledger_path: str | Path | None = None, cost_params: CostParams | None = None,
                 review_capacity: ReviewCapacity | None = None, alpha: float = 0.10):
        self.cp = cost_params or DATACO_COST
        self.capacity = review_capacity or ReviewCapacity(per_window=2, window_hours=4)
        self.ledger = AuditLedger(ledger_path) if ledger_path else None
        self.alpha = alpha
        self.model: RiskModel | None = None
        self.conformal: MondrianConformal | None = None
        self.coder: CategoryCoder | None = None
        self.thresholds: dict[str, float] = {}
        self.known: pd.DataFrame | None = None       # orders whose history the live path may use

    # ------------------------------------------------------------------ offline
    def fit(self, orders: pd.DataFrame) -> "DataCoShield":
        """Train on the train split, calibrate on the first half of validation, fit the conformal
        calibrator and threshold baselines on the second half. Nothing from the test window is used."""
        F.assert_no_leak(COLS)
        tr, va, _ = F.split(orders)
        self.coder = CategoryCoder(tr)
        Xtr, Xva = self.coder.transform(tr), self.coder.transform(va)
        half = va.ts.quantile(0.5)
        a, b = (va.ts < half).values, (va.ts >= half).values
        self.model = RiskModel(COLS).fit(Xtr, tr.is_fraud.values)
        self.model.calibrate(Xva[a], va.is_fraud.values[a])
        p_b, y_b = self.model.predict_proba(Xva[b]), va.is_fraud.values[b]
        self.conformal = MondrianConformal().fit(p_b, y_b)
        neg = np.sort(p_b[y_b == 0])[::-1]
        self.thresholds = {k: float(neg[min(int(q * len(neg)), len(neg) - 1)])
                           for k, q in [("fpr_0_5pct", 0.005), ("fpr_1pct", 0.01), ("fpr_2pct", 0.02)]}
        self.known = orders[orders.ts < pd.Timestamp(F.SPLITS["test"][0])].copy()
        self.training_summary = dict(train=len(tr), train_fraud=int(tr.is_fraud.sum()), calib=int(a.sum()),
                                     conformal=int(b.sum()), model_version=self.model.version)
        return self

    # ------------------------------------------------------------------ online
    def features(self, order: dict) -> dict:
        return self.coder.transform(pd.DataFrame([order])).iloc[0].to_dict()

    def reasons(self, f: dict, k: int = 4) -> list[dict]:
        """Top-k features pushing the risk up (TreeSHAP log-odds contributions)."""
        c = self.model.contributions(f).sort_values(ascending=False).head(k)
        return [dict(feature=n, label=LABELS.get(n, n.replace("_", " ")), value=self.coder.decode(n, f[n]),
                     contribution=round(float(v), 4)) for n, v in c.items() if v > 0]

    def score(self, order: dict, f: dict | None = None, explain: bool = False) -> dict:
        """Score one order-level row (from `to_orders` + `add_history`, or `order_from_items` + `history_for`)."""
        f = f if f is not None else self.features(order)
        ts = pd.Timestamp(order["ts"])
        charge, ltv = charge_and_ltv(order)
        p = self.model.predict_one(f)
        rr = evaluate_rules(f)
        conf = self.conformal.prediction_set(p, self.alpha)
        dec = cost_sensitive(p, charge, ltv, self.cp, self.capacity, ts, rr.hard_block, conf)
        result = dict(
            booking_id=f"dataco-{order['order_id']}", customer_id=int(order["customer_id"]), ts=str(ts),
            charge_usd=round(charge, 2), ltv_usd=round(ltv, 2), p_fraud=p, rules=dict(score=rr.score, hits=rr.hits),
            conformal=conf, decision=dict(action=dec.action, expected_costs=dec.expected_costs, reason=dec.reason,
                                          policy=dec.policy),
            feature_version=FEATURE_VERSION, model_version=self.model.version, features=f)
        if self.ledger is not None:
            result["ledger_hash"] = self.ledger.append(result)
        if explain:
            result["reasons"] = self.reasons(f)
            result["rule_text"] = [RULE_TEXT[h] for h in rr.hits]
            weights = {r.code: r.weight for r in DATACO_RULES}
            result["rules_detail"] = [dict(code=h, text=RULE_TEXT[h], score=weights[h]) for h in rr.hits]
        return result

    def score_new(self, order: dict, explain: bool = True) -> dict:
        """Live path for an order the system has not seen: history features from `known`, then score.
        The order is added to `known` afterwards (outcome unknown until feedback)."""
        row = dict(order)
        row.update(F.history_for(self.known, row))
        r = self.score(row, explain=explain)
        new = pd.DataFrame([{**{c: row.get(c) for c in self.known.columns if c in row}, "is_fraud": 0, "is_cancel": 0}])
        new["ts"] = pd.Timestamp(row["ts"])
        self.known = pd.concat([self.known, new], ignore_index=True)
        return r

    # ------------------------------------------------------------------ persistence
    SAVED_FIELDS = ("coder", "model", "conformal", "thresholds", "training_summary", "cp", "alpha")

    def save(self, folder: str | Path, metadata: dict | None = None) -> Path:
        """Write the fitted components to <folder>/fraudshield_dataco.pkl and a readable metadata.json.
        The pickle needs the same pandas / scikit-learn / LightGBM major versions to load."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        blob = {k: getattr(self, k) for k in self.SAVED_FIELDS}
        blob["feature_version"] = FEATURE_VERSION
        (folder / "fraudshield_dataco.pkl").write_bytes(pickle.dumps(blob))
        meta = dict(model_version=self.model.version, feature_version=FEATURE_VERSION,
                    ruleset_version=RULESET_VERSION, features=COLS, thresholds=self.thresholds,
                    training=self.training_summary, alpha=self.alpha, **(metadata or {}))
        (folder / "metadata.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
        return folder / "fraudshield_dataco.pkl"

    @classmethod
    def load(cls, folder: str | Path, ledger_path: str | Path | None = None,
             review_capacity: ReviewCapacity | None = None) -> "DataCoShield":
        blob = pickle.loads((Path(folder) / "fraudshield_dataco.pkl").read_bytes())
        if blob.get("feature_version") != FEATURE_VERSION:
            raise ValueError(f"saved model uses features {blob.get('feature_version')}, code expects "
                             f"{FEATURE_VERSION}; retrain with train_dataco.py")
        shield = cls(ledger_path=ledger_path, cost_params=blob["cp"], review_capacity=review_capacity,
                     alpha=blob["alpha"])
        for k in cls.SAVED_FIELDS:
            setattr(shield, k, blob[k])
        return shield

