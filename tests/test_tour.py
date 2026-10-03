"""Guided demo: every chapter gives its expected outcomes, and runs are repeatable after a reset.

Run: python3 -m pytest tests/ -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prototypes" / "fraudshield-pipeline"))
sys.path.insert(0, str(ROOT / "prototypes" / "data"))
import dataco_features as F  # noqa: E402
from fraudshield import tour  # noqa: E402
from fraudshield.bookings import BookingDesk  # noqa: E402
from fraudshield.dataco import DataCoShield  # noqa: E402
from fraudshield.decision import ReviewCapacity  # noqa: E402

MODEL_DIR = ROOT / "models" / "dataco"
pytestmark = pytest.mark.skipif(not (MODEL_DIR / "fraudshield_dataco.pkl").exists() or not F.DATA_PATH.exists(),
                                reason="saved model or cleaned_dataco.csv not present")

EXPECTED = {
    "ml_model": [("CONFIRMED", "ML model"), ("UNDER_REVIEW", "ML model"), ("VERIFICATION_REQUIRED", "ML model")],
    "rules": [("VERIFICATION_REQUIRED", "expert rules"), ("UNDER_REVIEW", "expert rules"),
              ("BLOCKED", "expert rule (always stops)")],
    "adds_up": [("BLOCKED", "expert rules")],
    "feedback": [("UNDER_REVIEW", "expert rules"), ("BLOCKED", "a person"), ("BLOCKED", "expert rule (always stops)")],
    "verify": [("VERIFICATION_REQUIRED", "expert rules"), ("VERIFICATION_REQUIRED", "the customer"),
               ("CONFIRMED", "the customer")],
    "explain": [("BLOCKED", "expert rules")],
}


@pytest.fixture(scope="module")
def data():
    return F.cached_orders(), F.load_items()


def fresh_desk(data, tmp_path):
    orders, items = data
    shield = DataCoShield.load(MODEL_DIR, ledger_path=tmp_path / "ledger.jsonl", review_capacity=ReviewCapacity(10, 4))
    return BookingDesk(shield, orders, items)


def run_all(desk):
    return {c["key"]: tour.run(desk, c["key"]) for c in tour.listing()}


def summary(results):
    return {k: [(s["booking"]["status"], s["decided_by"], round(s["booking"]["overall_risk"], 4)) for s in r["steps"]]
            for k, r in results.items()}


def test_every_chapter_gives_expected_outcomes(data, tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUDSHIELD_LLM", "0")
    results = run_all(fresh_desk(data, tmp_path))
    for key, want in EXPECTED.items():
        got = [(s["booking"]["status"], s["decided_by"]) for s in results[key]["steps"]]
        assert got == want, key


def test_feedback_chapter_learns_the_card(data, tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUDSHIELD_LLM", "0")
    desk = fresh_desk(data, tmp_path)
    steps = tour.run(desk, "feedback")["steps"]
    assert steps[1]["booking"]["confirmed_fraud"] is True
    assert [h["code"] for h in steps[2]["booking"]["rules_matched"]] == ["R08_CONFIRMED_FRAUD_PAYMENT"]
    assert desk.signals.payment_fraud[tour.CH4_CARD] == 1


def test_step_snapshots_do_not_change_later(data, tmp_path, monkeypatch):
    """Step 1 of the feedback chapter must still show 'under review', not the later rejection."""
    monkeypatch.setenv("FRAUDSHIELD_LLM", "0")
    steps = tour.run(fresh_desk(data, tmp_path), "feedback")["steps"]
    assert steps[0]["booking"]["status"] == "UNDER_REVIEW"
    assert all(e["status"] != "BLOCKED" for e in steps[0]["booking"]["events"])


def test_reset_makes_the_demo_repeatable(data, tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUDSHIELD_LLM", "0")
    first = summary(run_all(fresh_desk(data, tmp_path / "a")))
    second = summary(run_all(fresh_desk(data, tmp_path / "b")))
    assert first == second


def test_explain_chapter_reports_a_valid_audit_log(data, tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUDSHIELD_LLM", "0")
    step = tour.run(fresh_desk(data, tmp_path), "explain")["steps"][0]
    assert step["audit"]["valid"] and step["audit"]["records"] > 0
    assert step["explanation"]["source"] == "template" and "85%" in step["explanation"]["text"]
