"""Server-side Razorpay checkout and SES SMTP verification for the local portal."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import hashlib
import hmac
import json
import math
import secrets
import smtplib
import ssl
import threading
import time
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException, Request as FastAPIRequest
from pydantic import BaseModel, ConfigDict, Field

from .genai import _env

router = APIRouter()
RAZORPAY_API = "https://api.razorpay.com/v1"
_orders: dict[str, dict] = {}
_submission_orders: dict[str, str] = {}
_paid_receipts: dict[str, dict] = {}
_order_lock = threading.Lock()
_codes: dict[str, dict] = {}
_code_lock = threading.Lock()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class OrderRequest(StrictModel):
    submission_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    weight: float = Field(gt=0, le=200)
    length: float = Field(gt=0, le=300)
    width: float = Field(gt=0, le=300)
    height: float = Field(gt=0, le=300)
    collection: Literal["Pickup", "Drop-off"]
    protection: Literal["Basic", "Additional"]
    declared_value: int = Field(ge=0, le=10_000_000)
    discount: bool = False


class CheckoutVerification(StrictModel):
    order_id: str = Field(pattern=r"^order_[A-Za-z0-9]+$")
    payment_id: str = Field(pattern=r"^pay_[A-Za-z0-9]+$")
    signature: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class EmailCodeRequest(StrictModel):
    shipment_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)


class VerifyCodeRequest(EmailCodeRequest):
    code: str = Field(pattern=r"^[0-9]{6}$")


class NoticeRequest(StrictModel):
    shipment_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    status: Literal["Allowed", "Verification Required", "Awaiting Approval"]


class AdminInviteRequest(StrictModel):
    code: str = Field(min_length=12, max_length=256)


class DeviceRequest(StrictModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    device_type: Literal["desktop", "mobile", "tablet"]


class DeviceCodeRequest(DeviceRequest):
    code: str = Field(pattern=r"^[0-9]{6}$")


_device_lock = threading.Lock()
_memory_devices: dict[str, str] = {}
_memory_device_codes: dict[str, dict] = {}


def _connect_database():
    dsn = _env("DATABASE_URL")
    if not dsn:
        return None
    try:
        import psycopg
        return psycopg.connect(dsn, connect_timeout=5)
    except Exception:
        raise HTTPException(503, "The account database is unavailable. Try again shortly.") from None


def init_device_store() -> None:
    connection = _connect_database()
    if connection is None:
        return
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS portal_device_profiles (
                    email TEXT PRIMARY KEY,
                    last_accessed_device_type TEXT NOT NULL CHECK (last_accessed_device_type IN ('desktop','mobile','tablet')),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS portal_device_codes (
                    email TEXT PRIMARY KEY,
                    device_type TEXT NOT NULL CHECK (device_type IN ('desktop','mobile','tablet')),
                    code_hash BYTEA NOT NULL,
                    sent_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0
                )
            """)
    finally:
        connection.close()


def _known_device(email: str) -> str | None:
    connection = _connect_database()
    if connection is None:
        return _memory_devices.get(email)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("SELECT last_accessed_device_type FROM portal_device_profiles WHERE email = %s", (email,))
            row = cursor.fetchone()
            return row[0] if row else None
    finally:
        connection.close()


def _pending_device_code(email: str) -> dict | None:
    connection = _connect_database()
    if connection is None:
        return _memory_device_codes.get(email)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("SELECT device_type, code_hash, sent_at, expires_at, attempts FROM portal_device_codes WHERE email = %s", (email,))
            row = cursor.fetchone()
            return {"device_type": row[0], "digest": bytes(row[1]), "sent_at": row[2],
                    "expires_at": row[3], "attempts": row[4]} if row else None
    finally:
        connection.close()


def _save_device_code(email: str, device_type: str, digest: bytes, now: datetime) -> None:
    connection = _connect_database()
    if connection is None:
        _memory_device_codes[email] = {"device_type": device_type, "digest": digest,
            "sent_at": now, "expires_at": now + timedelta(minutes=10), "attempts": 0}
        return
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO portal_device_codes(email, device_type, code_hash, sent_at, expires_at, attempts)
                VALUES (%s, %s, %s, %s, %s, 0)
                ON CONFLICT(email) DO UPDATE SET device_type=EXCLUDED.device_type,
                  code_hash=EXCLUDED.code_hash, sent_at=EXCLUDED.sent_at,
                  expires_at=EXCLUDED.expires_at, attempts=0
            """, (email, device_type, digest, now, now + timedelta(minutes=10)))
    finally:
        connection.close()


def _update_device_attempt(email: str, attempts: int) -> None:
    connection = _connect_database()
    if connection is None:
        if email in _memory_device_codes:
            _memory_device_codes[email]["attempts"] = attempts
        return
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("UPDATE portal_device_codes SET attempts = %s WHERE email = %s", (attempts, email))
    finally:
        connection.close()


def _remember_device(email: str, device_type: str) -> None:
    connection = _connect_database()
    if connection is None:
        _memory_devices[email] = device_type
        return
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO portal_device_profiles(email, last_accessed_device_type)
                VALUES (%s, %s)
                ON CONFLICT(email) DO UPDATE SET last_accessed_device_type=EXCLUDED.last_accessed_device_type,
                  updated_at=now()
            """, (email, device_type))
            cursor.execute("DELETE FROM portal_device_codes WHERE email = %s", (email,))
    finally:
        connection.close()


def _delete_device_code(email: str) -> None:
    connection = _connect_database()
    if connection is None:
        _memory_device_codes.pop(email, None)
        return
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM portal_device_codes WHERE email = %s", (email,))
    finally:
        connection.close()


def _required(name: str) -> str:
    value = _env(name)
    if not value:
        raise HTTPException(503, f"{name} is not configured on the server.")
    return value


def _round(value: float) -> int:
    return math.floor(value + 0.5)


def _price(request: OrderRequest) -> int:
    shipping = _round(149 + max(request.weight, request.length * request.width * request.height / 5000) * 70)
    pickup = 79 if request.collection == "Pickup" else 0
    protection = _round(max(49, request.declared_value * 0.01)) if request.protection == "Additional" else 0
    discount = min(100, _round(shipping * 0.1)) if request.discount else 0
    return max(1, shipping + pickup + protection - discount)


def _razorpay(method: str, path: str, body: dict | None = None) -> dict:
    key_id = _required("RAZORPAY_KEY_ID")
    secret = _required("RAZORPAY_KEY_SECRET")
    payload = json.dumps(body).encode() if body is not None else None
    request = Request(f"{RAZORPAY_API}{path}", data=payload, method=method, headers={
        "Authorization": "Basic " + __import__("base64").b64encode(f"{key_id}:{secret}".encode()).decode(),
        "Content-Type": "application/json",
    })
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read(100_000).decode())
    except HTTPError as error:
        # Do not expose provider response bodies or credentials to the browser.
        raise HTTPException(502, "Razorpay could not complete the payment request. Check the server configuration and try again.") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise HTTPException(502, "Razorpay is temporarily unavailable. Try again shortly.") from None


@router.get("/payments/config")
def payment_config():
    key_id = _env("RAZORPAY_KEY_ID")
    return {"enabled": bool(key_id and _env("RAZORPAY_KEY_SECRET")), "key_id": key_id or None, "currency": "INR",
            "avs": "Razorpay AVS is applied by Razorpay when enabled for eligible international cards."}


@router.post("/auth/admin-invite/validate")
def validate_admin_invite(request: AdminInviteRequest):
    configured = _env("FRAUDSHIELD_ADMIN_INVITE_CODE")
    if not configured:
        raise HTTPException(503, "Admin account creation is disabled until the server invite code is configured.")
    if not hmac.compare_digest(configured.encode(), request.code.encode()):
        raise HTTPException(403, "That admin invite code is not valid.")
    return {"valid": True}


@router.post("/auth/device/enroll")
def enroll_initial_device(request: DeviceRequest):
    email = request.email.lower()
    _remember_device(email, request.device_type)
    return {"saved": True, "last_accessed_device_type": request.device_type}


@router.post("/auth/device/check")
def check_login_device(request: DeviceRequest):
    email = request.email.lower()
    previous = _known_device(email)
    if previous == request.device_type:
        return {"verification_required": False, "last_accessed_device_type": previous}
    now = datetime.now(timezone.utc)
    with _device_lock:
        pending = _pending_device_code(email)
        if pending and pending["device_type"] == request.device_type and now - pending["sent_at"] < timedelta(seconds=45):
            return {"verification_required": True, "destination": email, "retry_after_seconds": 45}
        code = f"{secrets.randbelow(1_000_000):06d}"
        _ses_send(email, "Confirm your new FraudShield sign-in device",
                  f"Your sign-in code is {code}. It expires in 10 minutes. If you did not try to sign in, ignore this email.")
        _save_device_code(email, request.device_type, hashlib.sha256(code.encode()).digest(), now)
    return {"verification_required": True, "destination": email, "retry_after_seconds": 45}


@router.post("/auth/device/verify")
def verify_login_device(request: DeviceCodeRequest):
    email = request.email.lower()
    with _device_lock:
        pending = _pending_device_code(email)
        now = datetime.now(timezone.utc)
        if (not pending or pending["device_type"] != request.device_type
                or now > pending["expires_at"] or pending["attempts"] >= 5):
            _delete_device_code(email)
            raise HTTPException(400, "That sign-in code expired. Request a new code and try again.")
        attempts = pending["attempts"] + 1
        if not hmac.compare_digest(pending["digest"], hashlib.sha256(request.code.encode()).digest()):
            _update_device_attempt(email, attempts)
            raise HTTPException(400, "That sign-in code did not match. Check the email and try again.")
        _remember_device(email, request.device_type)
        _delete_device_code(email)
    return {"verified": True, "last_accessed_device_type": request.device_type}


@router.post("/payments/razorpay/order")
def create_order(request: OrderRequest):
    key_id = _required("RAZORPAY_KEY_ID")
    amount = _price(request) * 100
    with _order_lock:
        paid = _paid_receipts.get(request.submission_id)
        if paid:
            return {"status": "Paid", "receipt": paid}
        existing_id = _submission_orders.get(request.submission_id)
        existing = _orders.get(existing_id or "")
        if existing and time.monotonic() - existing["created"] <= 1800:
            if existing["amount"] != amount:
                raise HTTPException(409, "This shipment changed after checkout began. Start a new shipment confirmation.")
            return {"key_id": key_id, "order_id": existing_id, "amount": amount, "currency": "INR"}
    receipt = "FS-" + request.submission_id.replace("-", "")[:35]
    result = _razorpay("POST", "/orders", {"amount": amount, "currency": "INR", "receipt": receipt,
                                             "notes": {"submission_id": request.submission_id}})
    if result.get("currency") != "INR" or result.get("amount") != amount or not result.get("id", "").startswith("order_"):
        raise HTTPException(502, "Razorpay returned an invalid order. No booking was submitted.")
    with _order_lock:
        _orders[result["id"]] = {"amount": amount, "currency": "INR", "submission_id": request.submission_id,
                                 "created": time.monotonic()}
        _submission_orders[request.submission_id] = result["id"]
        if len(_orders) > 500:
            oldest = min(_orders, key=lambda key: _orders[key]["created"])
            _orders.pop(oldest, None)
    return {"key_id": key_id, "order_id": result["id"], "amount": amount, "currency": "INR"}


@router.post("/payments/razorpay/verify")
def verify_payment(request: CheckoutVerification):
    secret = _required("RAZORPAY_KEY_SECRET")
    with _order_lock:
        expected_order = _orders.get(request.order_id)
    if not expected_order or time.monotonic() - expected_order["created"] > 1800:
        raise HTTPException(400, "This checkout expired. Start payment again.")
    expected = hmac.new(secret.encode(), f"{request.order_id}|{request.payment_id}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.signature):
        raise HTTPException(400, "Razorpay payment verification failed. The shipment was not submitted.")
    payment = _razorpay("GET", f"/payments/{request.payment_id}")
    if (payment.get("order_id") != request.order_id or payment.get("amount") != expected_order["amount"]
            or payment.get("currency") != expected_order["currency"]):
        raise HTTPException(400, "Razorpay has not confirmed the expected captured amount. The shipment was not submitted.")
    if payment.get("status") == "authorized":
        payment = _razorpay("POST", f"/payments/{request.payment_id}/capture", {"amount": expected_order["amount"], "currency": expected_order["currency"]})
    if payment.get("status") != "captured":
        raise HTTPException(400, "Razorpay has not confirmed a captured payment. The shipment was not submitted.")
    receipt = {"status": "Paid", "mode": "razorpay", "reference": request.payment_id,
            "order_id": request.order_id, "submission_id": expected_order["submission_id"],
            "amount": payment["amount"] // 100, "paid_at": datetime.now(timezone.utc).isoformat(),
            "avs": "Razorpay AVS is applied by Razorpay when enabled and supported by the card issuer."}
    with _order_lock:
        _paid_receipts[expected_order["submission_id"]] = receipt
        _orders.pop(request.order_id, None)
        _submission_orders.pop(expected_order["submission_id"], None)
    return receipt


def _ses_send(recipient: str, subject: str, body: str) -> None:
    host = _required("SES_SMTP_HOST")
    username = _required("SES_SMTP_USERNAME")
    password = _required("SES_SMTP_PASSWORD")
    sender = _required("SES_FROM_EMAIL")
    port = int(_env("SES_SMTP_PORT", "587"))
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=20) as client:
            client.starttls(context=ssl.create_default_context())
            client.login(username, password)
            client.send_message(message)
    except (smtplib.SMTPException, OSError, ValueError):
        raise HTTPException(502, "Email delivery is temporarily unavailable. Try sending the code again.") from None


@router.post("/verification/send-code")
def send_verification_code(request: EmailCodeRequest):
    key = request.shipment_id + ":" + request.email.lower()
    now = time.monotonic()
    with _code_lock:
        existing = _codes.get(key)
        if existing and now - existing["sent_at"] < 45:
            raise HTTPException(429, "Wait a little before requesting another code.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    _ses_send(request.email, "Your FraudShield shipment verification code",
              f"Your verification code for shipment {request.shipment_id} is {code}. It expires in 10 minutes. If you did not request it, you can ignore this email.")
    with _code_lock:
        _codes[key] = {"digest": hashlib.sha256(code.encode()).digest(), "sent_at": now,
                       "expires_at": now + 600, "attempts": 0}
    return {"sent": True, "expires_in_seconds": 600, "destination": request.email}


@router.post("/verification/verify-code")
def verify_code(request: VerifyCodeRequest):
    key = request.shipment_id + ":" + request.email.lower()
    with _code_lock:
        record = _codes.get(key)
        if not record or time.monotonic() > record["expires_at"] or record["attempts"] >= 5:
            _codes.pop(key, None)
            raise HTTPException(400, "That code expired. Request a new one and try again.")
        record["attempts"] += 1
        valid = hmac.compare_digest(record["digest"], hashlib.sha256(request.code.encode()).digest())
        if valid:
            _codes.pop(key, None)
    if not valid:
        raise HTTPException(400, "That code did not match. Check the email and try again.")
    return {"verified": True, "shipment_id": request.shipment_id}


@router.post("/notifications/shipment")
def email_shipment_update(request: NoticeRequest):
    subjects = {"Allowed": "Your shipment is approved", "Verification Required": "Verify your shipment",
                "Awaiting Approval": "Your shipment is under review"}
    body = {"Allowed": f"Shipment {request.shipment_id} passed the automatic checks and is approved to proceed.",
            "Verification Required": f"Shipment {request.shipment_id} needs an extra email verification step before it can proceed.",
            "Awaiting Approval": f"Shipment {request.shipment_id} needs an administrator to review it before it can proceed."}[request.status]
    _ses_send(request.email, subjects[request.status], body)
    return {"sent": True}


@router.post("/payments/razorpay/webhook")
async def razorpay_webhook(request: FastAPIRequest):
    secret = _required("RAZORPAY_WEBHOOK_SECRET")
    raw = await request.body()
    supplied = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(400, "Invalid Razorpay webhook signature.")
    # Captured-payment confirmation is handled synchronously by /verify for this demo.
    return {"received": True}
