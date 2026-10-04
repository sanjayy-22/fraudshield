"""Read-only adapter from the shipping portal to the saved DataCo model.

This is demonstration inference on a different input domain, not a validated
production shipping classifier. Missing information remains missing. In particular,
UPI/netbanking/card labels are NOT treated as DataCo's TRANSFER label, and a blocked
shipment is NOT treated as confirmed fraud. No ledger, history, or model is mutated.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .dataco import COLS, F, LABELS, DataCoShield

MODEL_DIR = Path(__file__).resolve().parents[3] / "models" / "dataco"


class PriorBooking(BaseModel):
    model_config = ConfigDict(extra="forbid")
    created: datetime
    value: float = Field(gt=0, le=10_000_000)
    city: str = Field(min_length=1, max_length=100)
    country: str = Field(min_length=1, max_length=100)

    @field_validator("created")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timestamps must include a timezone")
        return value


class PortalScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    booking_id: str = Field(min_length=1, max_length=80)
    created: datetime
    value: float = Field(gt=0, le=10_000_000)
    quantity: int = Field(ge=1, le=1000)
    category: str = Field(min_length=1, max_length=100)
    sender_country: str = Field(min_length=1, max_length=100)
    receiver_country: str = Field(min_length=1, max_length=100)
    receiver_city: str = Field(min_length=1, max_length=100)
    history: list[PriorBooking] = Field(default_factory=list, max_length=1000)

    @field_validator("created")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timestamps must include a timezone")
        return value


@lru_cache(maxsize=1)
def saved_model() -> DataCoShield:
    if not (MODEL_DIR / "fraudshield_dataco.pkl").exists():
        raise FileNotFoundError("Saved DataCo model is unavailable. Run train_dataco.py first.")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        shield = DataCoShield.load(MODEL_DIR)
    shield.portal_runtime_warnings = list(dict.fromkeys(str(w.message) for w in caught))
    return shield


def features_for(request: PortalScoreRequest, inr_per_usd: float) -> dict:
    if not np.isfinite(inr_per_usd) or inr_per_usd <= 0:
        raise ValueError("A positive demo INR/USD conversion factor is required")
    # The model supports NaN. Unknown values must never masquerade as observed zeros.
    features = {name: ("__unknown__" if name in F.CAT_COLS else np.nan) for name in COLS}
    history = [h for h in request.history if h.created < request.created]
    value = request.value / inr_per_usd
    prior_spend = sum(h.value for h in history) / inr_per_usd
    times = [(request.created - h.created).total_seconds() / 86400 for h in history]
    features.update(
        n_items=1, n_units=request.quantity, n_categories=1,
        gross_sales=value, net_total=value, max_unit_price=value / request.quantity,
        order_hour=request.created.hour, order_weekday=request.created.weekday(), order_day=request.created.day,
        customer_country=request.sender_country, main_category=request.category,
        cust_n_prior=len(history), cust_days_since_last=min(times) if times else -1,
        cust_prior_spend=prior_spend,
        cust_spend_ratio=value / (prior_spend / len(history)) if history and prior_spend else -1,
        cust_orders_7d=sum(t <= 7 for t in times), cust_orders_30d=sum(t <= 30 for t in times),
        cust_new_country=int(not any(h.country.casefold() == request.receiver_country.casefold() for h in history)),
        cust_new_city=int(not any(h.city.casefold() == request.receiver_city.casefold() for h in history)),
    )
    F.assert_no_leak(list(features))
    return features


def score_request(request: PortalScoreRequest, inr_per_usd: float) -> dict:
    shield = saved_model()
    features = features_for(request, inr_per_usd)
    vector = shield.coder.transform(pd.DataFrame([features])).iloc[0].to_dict()
    probability = shield.model.predict_one(vector)
    if not np.isfinite(probability):
        raise ValueError("The model returned a non-finite probability")
    contributions = shield.model.contributions(vector)
    contributions = contributions.loc[contributions.abs().sort_values(ascending=False).index].head(6)
    missing = [c for c in COLS if c not in F.CAT_COLS and pd.isna(features[c])]
    unknown_categories = [c for c in F.CAT_COLS if vector[c] == -1]
    return {
        "booking_id": request.booking_id,
        "source": "trained",
        "probability": probability,
        "model_version": shield.model.version,
        "feature_version": "portal-to-dataco-v1",
        "scored_at": datetime.now().astimezone().isoformat(),
        "shap": [{"name": LABELS.get(name, name.replace("_", " ")) + (" (unknown)" if name in missing + unknown_categories else ""), "value": float(value)}
                 for name, value in contributions.items()],
        "missing_features": missing,
        "unknown_categories": unknown_categories,
        "assumptions": [
            "Actual saved LightGBM inference; not validated for these logistics inputs.",
            f"Contents value is an order-value proxy converted with a fixed demo rate of INR {inr_per_usd:g}/USD, not a live exchange rate.",
            "Unavailable profit, outcome history and DataCo payment-type fields remain missing; UPI and netbanking are not mapped to TRANSFER.",
            "History is supplied by this browser demo and is not a trusted production feature store.",
            "The saved model ranked TRANSFER fraud close to chance on DataCo (ROC-AUC about 0.51).",
        ] + getattr(shield, "portal_runtime_warnings", []),
    }
