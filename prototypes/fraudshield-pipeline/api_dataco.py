"""FastAPI scoring service on real DataCo orders.

    uvicorn api_dataco:app --port 8081
    GET  /dataco/orders/{order_id}  score an existing test-window order (2017-07 → 2018-01), with the true label
    POST /dataco/score              score a new order from booking-time fields + items (leak fields → 422)
    GET  /dataco/summary            policy comparison + experiment headline numbers (from demo_dataco.py)
    GET  /dataco/ledger/verify      hash-chain check of this service's ledger
    GET  /health

On start-up the service fits DataCoShield on 2015 → 2017-H1 (nothing from the test window), the
same model demo_dataco.py replays. Decisions are appended to ledger_dataco_api.jsonl.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "data"))
import dataco_features as F                       # noqa: E402
from fraudshield.dataco import DataCoShield       # noqa: E402

app = FastAPI(title="FraudShield: DataCo scoring service", version="0.2.0")
STATE: dict[str, Any] = {"shield": None, "orders": None}

LEAK_FIELDS = sorted(set(F.LEAK_COLS) | {"is_fraud", "late_delivery_risk", "days_for_shipping_real"})


@app.on_event("startup")
def _startup():
    orders = F.cached_orders()
    ledger = HERE / "ledger_dataco_api.jsonl"
    if ledger.exists():
        ledger.unlink()
    STATE["shield"] = DataCoShield(ledger_path=ledger).fit(orders)
    STATE["orders"] = orders.set_index("order_id")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
def health():
    s = STATE["shield"]
    return dict(status="ok", model_version=s.model.version if s else None,
                trained_on=s.training_summary if s else None, thresholds=s.thresholds if s else None)


def _public(r: dict, extra: dict | None = None) -> dict:
    keep = ("booking_id", "p_fraud", "rules", "rule_text", "conformal", "decision", "reasons", "charge_usd", "ltv_usd",
            "model_version", "feature_version", "ledger_hash")
    out = {k: r[k] for k in keep if k in r}
    out.update(extra or {})
    return out


@app.get("/dataco/orders/{order_id}")
def score_existing(order_id: int):
    """Score an order from the replay window using its precomputed point-in-time features."""
    orders = STATE["orders"]
    if order_id not in orders.index:
        raise HTTPException(404, "unknown order_id")
    row = orders.loc[order_id]
    if row.split != "test":
        raise HTTPException(400, f"order {order_id} is in the '{row.split}' split; only test-window orders "
                                 f"({F.SPLITS['test'][0]} → {F.SPLITS['test'][1]}) can be scored here")
    order = row.to_dict() | {"order_id": order_id}
    r = STATE["shield"].score(order, explain=True)
    return _public(r, dict(truth=dict(is_fraud=bool(row.is_fraud), order_status=row.order_status,
                                      note="truth is shown for the demo only; it is never a model input"),
                           payment_type=row.payment_type, ts=str(row.ts)))


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quantity: float = Field(gt=0)
    unit_price: float = Field(ge=0)
    discount: float = Field(0.0, ge=0)
    discount_rate: float = Field(0.0, ge=0, le=1)
    profit: float = 0.0
    profit_ratio: float = 0.0
    category: str
    department: str
    product_id: int = -1


class NewOrder(BaseModel):
    """Only what is known when the order is placed. Post-booking fields are rejected."""
    model_config = ConfigDict(extra="forbid")
    order_id: int
    ts: str
    customer_id: int
    payment_type: str = Field(pattern="^(CASH|DEBIT|PAYMENT|TRANSFER)$")
    shipping_mode: str
    days_shipment_scheduled: int
    market: str
    order_region: str
    order_country: str
    order_city: str
    customer_segment: str
    customer_country: str
    customer_city: str
    items: list[Item] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _no_leaks(cls, data):
        if isinstance(data, dict):
            leaked = sorted(k for k in data if k in LEAK_FIELDS)
            if leaked:
                raise ValueError(f"leak fields not allowed at booking time: {leaked}. These are only known after "
                                 "the order is processed (see notes/comparison-dataco.md).")
        return data


@app.post("/dataco/score")
def score_new(o: NewOrder):
    shield = STATE["shield"]
    if pd.Timestamp(o.ts) < shield.known.ts.max():
        raise HTTPException(400, f"ts must not be earlier than the latest known order ({shield.known.ts.max()}); "
                                 "the live path only moves forward in time")
    header = o.model_dump(exclude={"items"})
    order = F.order_from_items(header, [i.model_dump() for i in o.items])
    r = shield.score_new(order, explain=True)
    return _public(r, dict(history={c: r["features"][c] for c in F.HISTORY_COLS}))


@app.get("/dataco/summary")
def summary():
    f = HERE / "stats_dataco.json"
    if not f.exists():
        raise HTTPException(404, "run demo_dataco.py first")
    s = json.loads(f.read_text(encoding="utf-8"))
    return dict(window=s["window"], policies=s["policies"], fraud_at_risk_usd=s["fraud_at_risk_usd"],
                experiments=s["experiments"], ledger=s["ledger"],
                assumptions="USD order value; LTV = max(2 × prior spend, order value); analyst review $5; "
                            "step-up and review outcomes simulated from CostParams")


@app.get("/dataco/ledger/verify")
def ledger_verify():
    ok, n = STATE["shield"].ledger.verify()
    return dict(valid=ok, records=n)
