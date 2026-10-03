"""FastAPI service on real DataCo orders: booking desk + scoring.

    uvicorn api_dataco:app --port 8081        (run from prototypes/fraudshield-pipeline)

Booking flow (used by frontend/):
    GET  /dataco/options                       dropdown data: products, countries, cities, payment types, clock
    GET  /dataco/customers/{customer_id}       an existing customer's segment and home city
    POST /dataco/bookings                      place a booking → CONFIRMED / VERIFICATION_REQUIRED / UNDER_REVIEW / BLOCKED
    GET  /dataco/bookings, /dataco/bookings/{id}
    POST /dataco/bookings/{id}/verify          {"code": "123456"} for VERIFICATION_REQUIRED
    GET  /dataco/review-queue                  bookings waiting for an analyst
    POST /dataco/bookings/{id}/review          {"approve": true|false, "note": "..."} for UNDER_REVIEW
Scoring and audit:
    GET  /dataco/orders/{order_id}             score an existing test-window order (2017-07 → 2018-01), with the true label
    POST /dataco/score                         score a raw order (header + items); leak fields → 422
    GET  /dataco/summary, /dataco/ledger/verify, /health

At start-up the service loads models/dataco/fraudshield_dataco.pkl (written by train_dataco.py).
If that file is missing it trains the same model in about 15 s. Decisions and state changes are
appended to ledger_dataco_api.jsonl.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "data"))
import dataco_features as F                       # noqa: E402
from fraudshield.bookings import BookingDesk, BookingError   # noqa: E402
from fraudshield.dataco import DataCoShield       # noqa: E402
from fraudshield.decision import ReviewCapacity   # noqa: E402

MODEL_DIR = HERE.parents[1] / "models" / "dataco"
# analyst reviews available per 4-hour window of the dataset clock (the replay uses 2; a demo needs more
# so the HOLD path stays visible): FRAUDSHIELD_REVIEWS_PER_4H=2 uvicorn api_dataco:app ...
REVIEWS_PER_4H = int(os.environ.get("FRAUDSHIELD_REVIEWS_PER_4H", "10"))

app = FastAPI(title="FraudShield: DataCo booking desk", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
                   allow_methods=["*"], allow_headers=["*"])
STATE: dict[str, Any] = {"shield": None, "orders": None, "desk": None, "model_source": None}

LEAK_FIELDS = sorted(set(F.LEAK_COLS) | {"is_fraud", "late_delivery_risk", "days_for_shipping_real"})


@app.on_event("startup")
def _startup():
    orders = F.cached_orders()
    ledger = HERE / "ledger_dataco_api.jsonl"
    if ledger.exists():
        ledger.unlink()
    if (MODEL_DIR / "fraudshield_dataco.pkl").exists():
        shield = DataCoShield.load(MODEL_DIR, ledger_path=ledger, review_capacity=ReviewCapacity(REVIEWS_PER_4H, 4))
        STATE["model_source"] = f"loaded {MODEL_DIR / 'fraudshield_dataco.pkl'}"
    else:
        shield = DataCoShield(ledger_path=ledger, review_capacity=ReviewCapacity(REVIEWS_PER_4H, 4)).fit(orders)
        STATE["model_source"] = "trained at start-up (run train_dataco.py to save it)"
    print(f"FraudShield model {shield.model.version}: {STATE['model_source']}; {REVIEWS_PER_4H} reviews per 4 h")
    STATE["shield"] = shield
    STATE["orders"] = orders.set_index("order_id")
    STATE["desk"] = BookingDesk(shield, orders, F.load_items())


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
def health():
    s = STATE["shield"]
    return dict(status="ok", model_version=s.model.version if s else None, model_source=STATE["model_source"],
                trained_on=s.training_summary if s else None, thresholds=s.thresholds if s else None,
                clock=str(STATE["desk"].now()) if STATE["desk"] else None, reviews_per_4h=REVIEWS_PER_4H)


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


# ------------------------------------------------------------------ booking desk
class BookingLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int
    quantity: int = Field(ge=1, le=5)
    discount_rate: float = Field(0.0, ge=0, le=0.25)


class BookingForm(BaseModel):
    """What a customer fills in. Leave customer_id empty (or 0) for a new customer."""
    model_config = ConfigDict(extra="forbid")
    customer_id: int | None = None
    customer_segment: str | None = None
    customer_country: str | None = None
    customer_city: str | None = None
    payment_type: str
    shipping_mode: str
    order_country: str
    order_city: str
    items: list[BookingLine] = Field(min_length=1, max_length=5)

    @model_validator(mode="before")
    @classmethod
    def _no_leaks(cls, data):
        if isinstance(data, dict):
            leaked = sorted(k for k in data if k in LEAK_FIELDS)
            if leaked:
                raise ValueError(f"leak fields not allowed at booking time: {leaked}")
        return data


class VerifyBody(BaseModel):
    code: str = Field(min_length=1, max_length=12)


class ReviewBody(BaseModel):
    approve: bool
    note: str = Field("", max_length=300)


def _desk() -> BookingDesk:
    if STATE["desk"] is None:
        raise HTTPException(503, "the service is still starting")
    return STATE["desk"]


def _booking(booking_id: str):
    try:
        return _desk().get(booking_id)
    except KeyError:
        raise HTTPException(404, f"no booking {booking_id}")


@app.get("/dataco/options")
def options():
    return _desk().options()


@app.get("/dataco/customers/{customer_id}")
def customer(customer_id: int):
    c = _desk().customer(customer_id)
    if c is None:
        raise HTTPException(404, f"customer {customer_id} is not known")
    return c


@app.post("/dataco/bookings")
def create_booking(form: BookingForm):
    try:
        b = _desk().create(form.model_dump())
    except BookingError as e:
        raise HTTPException(400, str(e))
    return b.public(include_code=True)


@app.get("/dataco/bookings")
def list_bookings():
    return [b.public() for b in reversed(list(_desk().bookings.values()))]


@app.get("/dataco/bookings/{booking_id}")
def get_booking(booking_id: str):
    return _booking(booking_id).public(include_code=True)


@app.post("/dataco/bookings/{booking_id}/verify")
def verify_booking(booking_id: str, body: VerifyBody):
    _booking(booking_id)
    try:
        return _desk().verify(booking_id, body.code).public(include_code=True)
    except BookingError as e:
        raise HTTPException(409, str(e))


@app.get("/dataco/review-queue")
def review_queue():
    return [b.public() for b in _desk().queue()]


@app.post("/dataco/bookings/{booking_id}/review")
def review_booking(booking_id: str, body: ReviewBody):
    _booking(booking_id)
    try:
        return _desk().review(booking_id, body.approve, body.note).public()
    except BookingError as e:
        raise HTTPException(409, str(e))

