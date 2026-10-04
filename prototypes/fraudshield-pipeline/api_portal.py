"""Saved-model inference and portal verification services on port 8082.

python -m uvicorn api_portal:app --host 127.0.0.1 --port 8082
Frontend Vite or Nginx proxies /portal-api/* here. Portal booking and decision state
remains a local workflow demonstration. PostgreSQL stores verified device types and
pending login verification codes.
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException

from fraudshield.portal_risk import PortalScoreRequest, saved_model, score_request
from fraudshield.portal_explain import ExplanationRequest, explain_snapshot
from fraudshield.portal_services import init_device_store, router as services_router

app = FastAPI(title="FraudShield portal model adapter", version="1.0.0")
app.include_router(services_router)
log = logging.getLogger(__name__)


@app.on_event("startup")
def initialize_portal_database():
    init_device_store()


@app.post("/explain")
def explain(request: ExplanationRequest, refresh: bool = False):
    return explain_snapshot(request, refresh=refresh)


@app.get("/health")
def health():
    try:
        model = saved_model()
        return {"status": "ok", "model_version": model.model.version, "mode": "read-only demo inference"}
    except Exception:
        raise HTTPException(503, "Saved model unavailable") from None


@app.post("/score")
def score(request: PortalScoreRequest):
    try:
        return score_request(request, float(os.getenv("FRAUDSHIELD_DEMO_INR_PER_USD", "85")))
    except Exception:
        log.exception("Portal scoring unavailable")
        raise HTTPException(503, "Model scoring is unavailable. Keep the booking pending and retry.") from None
