"""FastAPI scoring service — the shape of the integration point with the booking system.

    uvicorn api:app --port 8080
    POST /score      booking JSON → decision (synchronous, on the booking path)
    GET  /explain/{booking_id}    grounded explanation (asynchronous / on demand)
    POST /feedback   {booking_id, outcome}   outcome ∈ confirmed_fraud | verified_legit | not_shipped | unknown
    GET  /ledger/verify           hash-chain check
    GET  /health

On start-up the service trains on the simulated history so the demo is self-contained;
in production `FraudShield.fit` runs offline and the model + store are loaded.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "data"))
from simulate import generate                       # noqa: E402
from fraudshield.pipeline import FraudShield        # noqa: E402

app = FastAPI(title="FraudShield scoring service", version="0.1.0")
STATE: dict[str, Any] = {"fs": None, "bookings": {}, "results": {}}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


class Booking(BaseModel):
    booking_id: str
    ts: str
    shipper_id: str
    cohort: str
    ltv: float
    account_age_days: float
    origin_city: str
    dest_city: str
    dest_address_id: str
    weight_kg: float
    service: str
    contents: str
    declared_value: float
    charge_inr: float
    payment_id: str
    pay_age_min: float
    device_id: str
    hour: float | None = None


class Feedback(BaseModel):
    booking_id: str
    outcome: str


@app.on_event("startup")
def _startup():
    df = generate(seed=7)
    history = df[df.ts < df.ts.quantile(0.70)]
    STATE["fs"] = FraudShield(ledger_path=HERE / "ledger_api.jsonl").fit(history)


@app.get("/health")
def health():
    fs = STATE["fs"]
    return dict(status="ok", model_version=fs.model.version if fs else None, thresholds=fs.thresholds if fs else None)


@app.post("/score")
def score(b: Booking):
    fs = STATE["fs"]
    d = b.model_dump()
    d["ts"] = pd.Timestamp(d["ts"])
    if d["hour"] is None:
        d["hour"] = d["ts"].hour + d["ts"].minute / 60
    r = fs.score(d)
    STATE["bookings"][b.booking_id], STATE["results"][b.booking_id] = d, r
    return {k: r[k] for k in ("booking_id", "p_fraud", "rules", "conformal", "decision", "latency_ms", "model_version")}


@app.get("/explain/{booking_id}")
def explain(booking_id: str):
    r = STATE["results"].get(booking_id)
    if r is None:
        raise HTTPException(404, "unknown booking")
    return STATE["fs"].explain(r)


@app.post("/feedback")
def feedback(f: Feedback):
    b = STATE["bookings"].get(f.booking_id)
    if b is None:
        raise HTTPException(404, "unknown booking")
    STATE["fs"].feedback(b, f.outcome)
    return dict(ok=True)


@app.get("/ledger/verify")
def ledger_verify():
    ok, n = STATE["fs"].ledger.verify()
    return dict(valid=ok, records=n)
