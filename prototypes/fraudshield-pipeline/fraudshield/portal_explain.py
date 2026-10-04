"""Evidence-grounded Qwen wording for the portal; never changes scores or decisions.

This local demo receives a bounded snapshot from browser storage. It is not a
server-authoritative ledger. PII, booking descriptions, and free-text admin notes
are excluded from the provider payload. Production requires authenticated records.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from typing import Literal
import urllib.error
import urllib.request

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .genai import _env
from .dataco import COLS, LABELS

DEFAULT_MODEL = "qwen/qwen3.8-27b:free"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
SYSTEM_PROMPT = Path(__file__).with_name("portal_explain_system.txt").read_text(encoding="utf-8")
PROMPT_VERSION = "portal-explanation-v1"
RULES = {
    "New account": (10, "The account was created less than 30 days before booking."),
    "Unusual shipment value": (15, "Contents value is at least INR 50,000, and either exceeds three times the prior average or has no prior history for comparison."),
    "New device": (10, "The sample marks this as a device that has not been verified for this account."),
    "Multiple addresses": (5, "At least four destination cities occur across this booking and the previous seven days."),
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RuleHit(StrictModel):
    name: Literal["New account", "Unusual shipment value", "New device", "Multiple addresses"]
    points: int = Field(ge=0, le=40)


class Contribution(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    value: float = Field(ge=-1000, le=1000)


class RuleContext(StrictModel):
    account_age_days: float = Field(ge=0, le=100000)
    contents_value: float = Field(gt=0, le=10000000)
    prior_average_value: float = Field(ge=0, le=10000000)
    prior_bookings: int = Field(ge=0, le=1000000)
    recent_destination_count: int = Field(ge=1, le=1000000)


class RiskSnapshot(StrictModel):
    overall: int | None = Field(ge=0, le=100)
    ai: float | None = Field(ge=0, le=100)
    rule_score: int = Field(ge=0, le=40)
    rule_max: Literal[40] = 40
    source: Literal["trained", "simulated", "unavailable"]
    factors: list[RuleHit] = Field(max_length=4)
    shap: list[Contribution] = Field(default_factory=list, max_length=6)
    context: RuleContext | None = None

    @model_validator(mode="after")
    def consistent_score(self):
        names = [f.name for f in self.factors]
        if len(set(names)) != len(names) or any(f.points != RULES[f.name][0] for f in self.factors):
            raise ValueError("Invalid rule evidence")
        if self.rule_score != sum(f.points for f in self.factors):
            raise ValueError("Rule total does not match the recorded evidence")
        if self.source == "unavailable":
            if self.overall is not None or self.ai is not None or self.shap:
                raise ValueError("Unavailable scores must remain unknown")
        else:
            if self.ai is None or self.overall is None:
                raise ValueError("A scored snapshot requires both scores")
            # The UI stores ML percentage to 2dp after calculating the overall score.
            raw = self.rule_score + .6 * self.ai
            if abs(self.overall - raw) > .504:
                raise ValueError("Overall score does not match the documented formula")
        if self.source != "simulated" and "New device" in names:
            raise ValueError("The portal does not collect device evidence")
        labels = set(RULES) | {"Established history"} if self.source == "simulated" else {
            LABELS.get(name, name.replace("_", " ")) + suffix
            for name in COLS for suffix in ("", " (unknown)")
        }
        if any(item.name not in labels for item in self.shap):
            raise ValueError("Unknown model feature label")
        if self.context and self.source != "simulated":
            c = self.context
            expected = {
                "New account": c.account_age_days < 30,
                "Unusual shipment value": c.contents_value >= 50000 and (c.prior_bookings == 0 or c.contents_value > 3 * c.prior_average_value),
                "Multiple addresses": c.recent_destination_count >= 4,
            }
            if any((name in names) != hit for name, hit in expected.items()):
                raise ValueError("Rule observations do not match the triggered rules")
        return self


class ExplanationRequest(StrictModel):
    booking_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    revision: int = Field(ge=1)
    status: Literal["Awaiting Approval", "Awaiting Verification", "On Hold", "Blocked", "Approved"]
    payment_status: Literal["Paid", "Failed"]
    dispatched: bool = False
    risk: RiskSnapshot
    decision_reason: Literal["Verified customer", "Risk factors resolved", "Additional verification completed", "Suspicious activity confirmed", "Other"] | None = None


def _card(key, kind, title, fact, impact=None, required_phrase=None):
    return dict(evidence_id=key, kind=kind, title=title, explanation=fact, fact=fact,
                impact=impact, required_phrase=required_phrase)


def build_cards(request: ExplanationRequest) -> list[dict]:
    r = request.risk
    if request.status == "Awaiting Approval":
        if r.overall is None:
            detail = "The risk score is unavailable, so an administrator must review this shipment before it can proceed."
        else:
            detail = f"The recorded risk score is {r.overall}/100. Scores of 60 or above need administrator review before the shipment can proceed."
        title = "Waiting for admin approval"
    elif request.status == "Awaiting Verification":
        detail = "This shipment needs the one-time code sent to the customer's email before it can proceed. Successful verification approves it automatically; no administrator approval is needed."
        title = "Email verification required"
    elif request.status == "Approved":
        detail = "An administrator approved this booking. Approval does not lower its recorded risk score or prove the customer's identity."
        title = "Approved by an administrator"
    elif request.status == "On Hold":
        detail = "An administrator placed this booking on hold for review. Shipping is paused; a hold is not a confirmed fraud finding."
        title = "On hold for review"
    else:
        detail = "An administrator blocked this booking from shipping. The block records a decision, not independent proof that the customer committed fraud."
        title = "Blocked by an administrator"
    if request.status not in ("Awaiting Approval", "Awaiting Verification"):
        detail += " Recorded reason: " + (request.decision_reason or "not available") + "."
    if request.dispatched:
        detail += " Dispatch has already been simulated."
    cards = [_card("status", "decision", title, detail)]
    if r.overall is None:
        cards.append(_card("score", "calculation", "Risk score unavailable", "The model score is unavailable, so the combined risk score cannot be calculated. Approval must wait for successful scoring."))
    else:
        band = "LOW" if r.overall < 30 else "MEDIUM" if r.overall < 60 else "HIGH" if r.overall < 80 else "CRITICAL"
        total = f"40% of the normalized rule score ({r.rule_score}/40) contributes {r.rule_score} points. 60% of the ML score ({r.ai:g}%) contributes approximately {.6 * r.ai:.2f} points. The recorded rounded total is {r.overall}/100 ({band})."
        total += " Scores of 60 or above appear in Suspicious while awaiting approval or on hold; a score does not automatically approve or block shipping."
        cards.append(_card("score", "calculation", "How the score adds up", total, f"{r.overall}/100"))
    if not r.factors:
        cards.append(_card("rules:none", "rule", "No configured rules matched", "No configured rule added points to this snapshot. This does not mean all possible fraud checks passed; the model score and missing evidence still need review."))
    for index, factor in enumerate(r.factors):
        phrase = "sample rule matched" if r.source == "simulated" else "rule matched"
        fact = f"The {phrase}: {RULES[factor.name][1]} It adds {factor.points} rule points."
        if r.context and r.source != "simulated":
            c = r.context
            if factor.name == "New account":
                fact += f" Recorded account age: {c.account_age_days:.2f} days."
            elif factor.name == "Unusual shipment value":
                fact += f" Recorded contents value: INR {c.contents_value:g}; prior bookings: {c.prior_bookings}; previous average: INR {c.prior_average_value:.2f}."
            elif factor.name == "Multiple addresses":
                fact += f" Recorded destination-city count: {c.recent_destination_count}."
        cards.append(_card(f"rule:{index}", "rule", factor.name, fact, f"+{factor.points} rule points", phrase))
    # Model labels are from the score snapshot, never customer-entered shipment text.
    for index, item in enumerate(sorted(r.shap, key=lambda item: abs(item.value), reverse=True)[:2]):
        direction = "raises model risk" if item.value > 0 else "lowers model risk" if item.value < 0 else "has no model impact"
        qualifier = "Sample contribution" if r.source == "simulated" else "Recorded model contribution"
        fact = f"{qualifier}: {item.name} {direction}."
        if "unknown" in item.name.lower():
            fact += " This input is unknown, so its model effect must not be read as a verified customer fact."
        fact += " This direction explains the model output; it is not an added rule or a percentage of the final score."
        cards.append(_card(f"model:{index}", "model", "Model factor: " + item.name, fact, direction, direction))
    limitation = ("This is seeded sample evidence, including any device signal. It is not observed evidence about a real customer." if r.source == "simulated" else "The saved DataCo model has not been validated for these shipping inputs. Missing inputs remain unknown; device, identity, and bank verification checks are not collected by this portal.")
    limitation += f" Payment status: {request.payment_status.lower()} in the demo. No real bank authentication or payment is established by that status."
    cards.append(_card("limits", "limitation", "What this evidence cannot confirm", limitation))
    return cards


class WrittenPoint(StrictModel):
    evidence_id: str = Field(max_length=30)
    title: str = Field(min_length=3, max_length=70)
    explanation: str = Field(min_length=10, max_length=400)


class WrittenExplanation(StrictModel):
    points: list[WrittenPoint] = Field(min_length=1, max_length=6)


def _numbers(value: str) -> set[float]:
    return {float(x.replace(",", "")) for x in re.findall(r"(?<!\w)[+-]?\d[\d,]*(?:\.\d+)?", value)}


def validate_wording(raw: str, cards: list[dict]) -> list[WrittenPoint]:
    result = WrittenExplanation.model_validate_json(raw)
    if [p.evidence_id for p in result.points] != [c["evidence_id"] for c in cards]:
        raise ValueError("Evidence references do not match")
    for point, card in zip(result.points, cards):
        text = point.title + " " + point.explanation
        if _numbers(text) - _numbers(card["fact"]):
            raise ValueError("Unsupported number")
        if card["required_phrase"] not in point.explanation.lower():
            raise ValueError("Missing evidence direction")
        if "unknown" in card["fact"].lower() and "unknown" not in point.explanation.lower():
            raise ValueError("Unknown input represented as observed")
        if "sample" in card["fact"].lower() and "sample" not in point.explanation.lower():
            raise ValueError("Sample evidence represented as observed")
        opposite = "lowers model risk" if card["required_phrase"] == "raises model risk" else "raises model risk" if card["required_phrase"] == "lowers model risk" else None
        if opposite and opposite in text.lower():
            raise ValueError("Reversed model effect")
        if re.search(r"<[^>]+>|https?://|\b(?:stolen|criminal|guaranteed|definitely|safe|innocent|guilty|OTP|CVV|CVC|AVS|automatically|confirmed fraud)\b|(?:not|never)\s+(?:\w+\s+){0,2}(?:rule matched|raises model risk|lowers model risk)", text, re.I):
            raise ValueError("Unsupported assertion")
    return result.points


def ask_qwen(cards: list[dict]) -> str:
    key = _env("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("not_configured")
    body = dict(model=_env("OPENROUTER_MODEL", DEFAULT_MODEL), temperature=.1, max_tokens=1800,
                reasoning={"enabled": False},
                messages=[dict(role="system", content=SYSTEM_PROMPT), dict(role="user", content=json.dumps(cards))],
                response_format={"type": "json_object"})
    # Fixed trusted destination: a user-supplied URL must never receive the credential.
    request = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "FraudShield Admin Explanations"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.loads(response.read(100000).decode())
    except urllib.error.HTTPError as error:
        # Never forward provider response bodies, credentials, or raw requests to the UI/logs.
        raise RuntimeError("rate_limited" if error.code == 429 else "provider_unavailable") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError("provider_unavailable") from None
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ValueError("Invalid provider response") from None


_cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_lock = threading.Lock()
_slots = threading.BoundedSemaphore(2)
NOTES = {
    "not_configured": "Qwen is not configured. Showing the recorded evidence explanation.",
    "disabled": "AI wording is turned off. Showing the recorded evidence explanation.",
    "rate_limited": "Qwen is temporarily rate-limited. Showing the recorded evidence explanation; try again later.",
    "provider_unavailable": "Qwen is unavailable. Showing the recorded evidence explanation; you can retry.",
    "invalid_response": "AI wording did not pass the evidence checks. Showing the recorded evidence explanation.",
    "busy": "AI explanation requests are busy. Showing the recorded evidence explanation.",
}


def explain_snapshot(request: ExplanationRequest, refresh: bool = False) -> dict:
    digest = hashlib.sha256((PROMPT_VERSION + (_env("OPENROUTER_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL) + request.model_dump_json()).encode()).hexdigest()
    now = time.monotonic()
    with _lock:
        cached = _cache.get(digest)
        if cached and now - cached[0] < (600 if cached[1]["source"] == "ai" else 20) and (not refresh or now - cached[0] < 5):
            _cache.move_to_end(digest)
            return cached[1]
    cards = build_cards(request)
    writable = [{k: card[k] for k in ("evidence_id", "title", "fact", "required_phrase")} for card in cards if card["required_phrase"]]
    source, note = "template", "Showing the recorded evidence explanation."
    if writable and _slots.acquire(blocking=False):
        try:
            if _env("FRAUDSHIELD_LLM", "1") == "0":
                raise RuntimeError("disabled")
            generated = validate_wording(ask_qwen(writable), writable)
            by_id = {p.evidence_id: p for p in generated}
            for card in cards:
                if card["evidence_id"] in by_id:
                    item = by_id[card["evidence_id"]]
                    card.update(title=item.title, explanation=item.explanation)
            source, note = "ai", "Qwen explains the recorded rule and model evidence. Score calculations and admin decisions come directly from the record."
        except RuntimeError as error:
            note = NOTES.get(str(error), NOTES["provider_unavailable"])
        except (ValueError, TypeError, KeyError):
            note = NOTES["invalid_response"]
        finally:
            _slots.release()
    elif writable:
        note = NOTES["busy"]
    result = dict(booking_id=request.booking_id, revision=request.revision, source=source,
                  model=_env("OPENROUTER_MODEL", DEFAULT_MODEL) if source == "ai" else None,
                  prompt_version=PROMPT_VERSION, generated_at=datetime.now(timezone.utc).isoformat(),
                  note=note, points=[{k: v for k, v in card.items() if k != "required_phrase"} for card in cards])
    with _lock:
        _cache[digest] = (time.monotonic(), result)
        _cache.move_to_end(digest)
        while len(_cache) > 128:
            _cache.popitem(last=False)
    return result
