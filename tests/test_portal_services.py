"""Server-side checkout and step-up service boundary tests; no live provider calls."""
import hashlib
import hmac
import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'prototypes' / 'fraudshield-pipeline'))
import api_portal
from fraudshield import portal_services as services

client = TestClient(api_portal.app)


def test_razorpay_order_computes_price_on_server(monkeypatch):
    monkeypatch.setattr(services, '_env', lambda name, default=None: {'RAZORPAY_KEY_ID': 'rzp_test_key', 'RAZORPAY_KEY_SECRET': 'server-secret'}.get(name, default))
    body = dict(submission_id='confirm-1234', weight=2.5, length=30, width=20, height=15,
                collection='Pickup', protection='Basic', declared_value=2500, discount=False)
    monkeypatch.setattr(services, '_razorpay', lambda method, path, payload: {
        'id': 'order_test123', 'amount': payload['amount'], 'currency': payload['currency']})
    response = client.post('/payments/razorpay/order', json=body)
    assert response.status_code == 200
    assert response.json() == {'key_id': 'rzp_test_key', 'order_id': 'order_test123', 'amount': 40300, 'currency': 'INR'}


def test_razorpay_payment_requires_valid_signature_and_capture(monkeypatch):
    secret = 'server-only-test-secret'
    monkeypatch.setattr(services, '_env', lambda name, default=None: secret if name == 'RAZORPAY_KEY_SECRET' else default)
    monkeypatch.setattr(services, '_orders', {'order_test456': {'amount': 40300, 'currency': 'INR', 'submission_id': 'confirm-5678', 'created': services.time.monotonic()}})
    monkeypatch.setattr(services, '_submission_orders', {'confirm-5678': 'order_test456'})
    monkeypatch.setattr(services, '_paid_receipts', {})
    calls = []
    def razorpay(method, path, body=None):
        calls.append((method, path, body))
        if method == 'GET': return {'order_id': 'order_test456', 'amount': 40300, 'currency': 'INR', 'status': 'authorized'}
        return {'order_id': 'order_test456', 'amount': 40300, 'currency': 'INR', 'status': 'captured'}
    monkeypatch.setattr(services, '_razorpay', razorpay)
    signature = hmac.new(secret.encode(), b'order_test456|pay_test789', hashlib.sha256).hexdigest()
    response = client.post('/payments/razorpay/verify', json={'order_id': 'order_test456', 'payment_id': 'pay_test789', 'signature': signature})
    assert response.status_code == 200
    assert response.json()['status'] == 'Paid'
    assert [call[0] for call in calls] == ['GET', 'POST']
    assert calls[1][2] == {'amount': 40300, 'currency': 'INR'}
    assert services._paid_receipts['confirm-5678']['reference'] == 'pay_test789'


def test_invalid_razorpay_signature_cannot_capture(monkeypatch):
    monkeypatch.setattr(services, '_env', lambda name, default=None: 'secret' if name == 'RAZORPAY_KEY_SECRET' else default)
    monkeypatch.setattr(services, '_orders', {'order_test456': {'amount': 40300, 'currency': 'INR', 'submission_id': 'confirm-5678', 'created': services.time.monotonic()}})
    called = []
    monkeypatch.setattr(services, '_razorpay', lambda *args, **kwargs: called.append(args))
    response = client.post('/payments/razorpay/verify', json={'order_id': 'order_test456', 'payment_id': 'pay_test789', 'signature': '0' * 64})
    assert response.status_code == 400
    assert called == []


def test_step_up_code_is_emailed_then_consumed_once(monkeypatch):
    deliveries = []
    monkeypatch.setattr(services, '_ses_send', lambda to, subject, body: deliveries.append((to, subject, body)))
    monkeypatch.setattr(services, '_codes', {})
    sent = client.post('/verification/send-code', json={'shipment_id': 'FS12345', 'email': 'customer@example.com'})
    assert sent.status_code == 200 and 'code' not in sent.json()
    assert deliveries[0][0] == 'customer@example.com'
    code = re.search(r'\b([0-9]{6})\b', deliveries[0][2]).group(1)
    verify = {'shipment_id': 'FS12345', 'email': 'customer@example.com', 'code': code}
    assert client.post('/verification/verify-code', json=verify).json()['verified'] is True
    assert client.post('/verification/verify-code', json=verify).status_code == 400


def test_admin_account_creation_requires_server_invite(monkeypatch):
    monkeypatch.setattr(services, '_env', lambda name, default=None: 'long-test-invite-code' if name == 'FRAUDSHIELD_ADMIN_INVITE_CODE' else default)
    assert client.post('/auth/admin-invite/validate', json={'code': 'long-test-invite-code'}).json()['valid'] is True
    assert client.post('/auth/admin-invite/validate', json={'code': 'wrong-invite-code'}).status_code == 403
