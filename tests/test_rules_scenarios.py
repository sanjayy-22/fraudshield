"""Shipment rules on the booking desk: every demo scenario, the risk arithmetic, the fraud feedback
loop, and the AI explanation (against a local mock of the OpenRouter API; no real network, no real key).

Run: python3 -m pytest tests/ -q
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prototypes" / "fraudshield-pipeline"))
sys.path.insert(0, str(ROOT / "prototypes" / "data"))
import dataco_features as F  # noqa: E402
from fraudshield import demo_scenarios, genai  # noqa: E402
from fraudshield.bookings import THRESHOLDS, BookingDesk  # noqa: E402
from fraudshield.dataco import DataCoShield  # noqa: E402
from fraudshield.decision import ReviewCapacity  # noqa: E402

MODEL_DIR = ROOT / "models" / "dataco"
pytestmark = pytest.mark.skipif(not (MODEL_DIR / "fraudshield_dataco.pkl").exists() or not F.DATA_PATH.exists(),
                                reason="saved model or cleaned_dataco.csv not present")


@pytest.fixture(scope="module")
def data():
    return F.cached_orders(), F.load_items()


@pytest.fixture
def desk(data, tmp_path):
    orders, items = data
    shield = DataCoShield.load(MODEL_DIR, ledger_path=tmp_path / "ledger.jsonl", review_capacity=ReviewCapacity(10, 4))
    return BookingDesk(shield, orders, items)


# ------------------------------------------------------------------ scenarios
@pytest.mark.parametrize("scenario", demo_scenarios.SCENARIOS, ids=lambda s: s.key)
def test_scenario_gives_expected_rules_and_outcome(desk, scenario):
    prep = demo_scenarios.prepare(desk, scenario.key)
    b = desk.create(prep["form"])
    assert {h["code"] for h in b.rules_matched} == set(scenario.rules)
    assert b.status == scenario.expect


def test_all_scenarios_in_one_session(desk):
    """The demo is run in one go: earlier scenarios (and clock jumps) must not change later ones."""
    for s in demo_scenarios.SCENARIOS:
        b = desk.create(demo_scenarios.prepare(desk, s.key)["form"])
        assert b.status == s.expect, s.key


def test_risk_adds_up_as_documented(desk):
    b = desk.create(demo_scenarios.prepare(desk, "card_device_night")["form"])
    expected = b.risk_steps[0]["after"]               # the model's exact probability
    assert expected == pytest.approx(b.model_risk, abs=1e-4)
    for h in b.rules_matched:
        assert h["before"] == pytest.approx(expected)
        expected = expected + (1 - expected) * h["weight"]
        assert h["after"] == pytest.approx(expected)
    assert b.overall_risk == pytest.approx(expected, abs=1e-4)
    rules_only = 1 - (1 - 0.6) * (1 - 0.7) * (1 - 0.4)
    assert b.rule_score == pytest.approx(rules_only, abs=1e-4)
    assert b.overall_risk >= THRESHOLDS["stop"] and b.status == "BLOCKED"
    assert "stop line" in b.decided_by          # stopped by the score, no hard rule


def test_plain_order_has_no_shipment_rules(desk):
    form = dict(customer_id=12366, payment_type="DEBIT", shipping_mode="First Class", order_country="El Salvador",
                order_city="San Salvador", items=[dict(product_id=957, quantity=1, discount_rate=0.05)])
    b = desk.create(form)
    assert b.rules_matched == [] and b.status == "CONFIRMED"


def test_confirmed_fraud_device_flags_the_next_order(desk):
    """Reject an order sent from a device → that device is now known fraud → R05 on another customer."""
    first = desk.create(demo_scenarios.prepare(desk, "new_card")["form"] | {"signals": {
        "payment_id": "CARD-NEW-4411", "payment_added_minutes_ago": 20, "device_id": "PHONE-X-1"}})
    assert first.status == "UNDER_REVIEW"
    desk.review(first.booking_id, approve=False, note="customer denied the order")
    assert first.confirmed_fraud and desk.signals.device_fraud["PHONE-X-1"] == 1
    prep = demo_scenarios.prepare(desk, "heavy")
    form = prep["form"] | {"signals": {"device_id": "PHONE-X-1"}}
    second = desk.create(form)
    assert "R05_SHARED_FRAUD_DEVICE" in {h["code"] for h in second.rules_matched}


def test_approved_order_becomes_normal_for_the_customer(desk):
    prep = demo_scenarios.prepare(desk, "night")
    b = desk.create(prep["form"])
    b = desk.verify(b.booking_id, b.verification_code)
    assert b.status == "CONFIRMED"
    assert "LAPTOP-UNKNOWN-7" in desk.signals.devices[b.customer_id]


# ------------------------------------------------------------------ AI explanation
class _Mock(BaseHTTPRequestHandler):
    reply = ""
    seen = {}

    def do_POST(self):  # noqa: N802
        n = int(self.headers["Content-Length"])
        _Mock.seen = dict(auth=self.headers.get("Authorization"), body=json.loads(self.rfile.read(n)))
        out = json.dumps({"choices": [{"message": {"content": _Mock.reply}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def mock_llm(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("OPENROUTER_URL", f"http://127.0.0.1:{srv.server_port}/v1/chat/completions")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/model")
    yield _Mock
    srv.shutdown()


def test_ai_explanation_used_when_numbers_check_out(desk, mock_llm):
    b = desk.create(demo_scenarios.prepare(desk, "burst_heavy")["form"])
    mock_llm.reply = ("<think>internal</think>We sent this order to a person because two warning signs added up. "
                      "A booking burst (50%) and an unusually heavy parcel (30%) took the risk to 65.0%, above the 60% "
                      "review line. We only stop an order as fraud from 85%.")
    out = genai.explain(b, THRESHOLDS)
    assert out["source"] == "ai" and "<think>" not in out["text"]
    assert mock_llm.seen["auth"] == "Bearer test-key-not-real"
    assert mock_llm.seen["body"]["model"] == "test/model"


def test_ai_explanation_with_invented_number_is_rejected(desk, mock_llm):
    b = desk.create(demo_scenarios.prepare(desk, "burst_heavy")["form"])
    mock_llm.reply = "The risk was 97% because of 12 earlier frauds."
    out = genai.explain(b, THRESHOLDS)
    assert out["source"] == "template" and "rejected" in out["note"]
    assert out["text"] == out["template"]


def test_template_used_without_key(desk, monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(genai, "ROOT", tmp_path)          # no .env there
    b = desk.create(demo_scenarios.prepare(desk, "heavy")["form"])
    out = genai.explain(b, THRESHOLDS)
    assert out["source"] == "template" and "no OPENROUTER_API_KEY" in out["note"]
    assert "30%" in out["text"] and "85%" in out["text"]
