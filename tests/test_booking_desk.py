"""Booking desk state machine on the saved DataCo model.

Run: python3 -m pytest tests/ -q   (needs models/dataco/fraudshield_dataco.pkl: python3 prototypes/fraudshield-pipeline/train_dataco.py)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prototypes" / "fraudshield-pipeline"))
sys.path.insert(0, str(ROOT / "prototypes" / "data"))
import dataco_features as F  # noqa: E402
from fraudshield.bookings import BookingDesk, BookingError  # noqa: E402
from fraudshield.dataco import DataCoShield  # noqa: E402
from fraudshield.decision import ReviewCapacity  # noqa: E402

MODEL_DIR = ROOT / "models" / "dataco"
pytestmark = pytest.mark.skipif(not (MODEL_DIR / "fraudshield_dataco.pkl").exists() or not F.DATA_PATH.exists(),
                                reason="saved model or cleaned_dataco.csv not present")

RETURNING = dict(customer_id=12366, shipping_mode="First Class", order_country="El Salvador", order_city="San Salvador",
                 items=[dict(product_id=957, quantity=1, discount_rate=0.05), dict(product_id=365, quantity=3, discount_rate=0.1)])
RISKY = dict(customer_id=16106, payment_type="TRANSFER", shipping_mode="Second Class", order_country="Países Bajos",
             order_city="Almelo", items=[dict(product_id=276, quantity=3, discount_rate=0),
                                         dict(product_id=172, quantity=5, discount_rate=0.25)])
FIXED_NOW = pd.Timestamp("2018-02-01 09:00")


@pytest.fixture(scope="module")
def data():
    return F.cached_orders(), F.load_items()


@pytest.fixture
def desk(data, tmp_path):
    orders, items = data
    shield = DataCoShield.load(MODEL_DIR, ledger_path=tmp_path / "ledger.jsonl", review_capacity=ReviewCapacity(10, 4))
    d = BookingDesk(shield, orders, items)
    d.now = lambda: FIXED_NOW          # the decision depends on the hour; pin it
    return d


def test_saved_model_matches_fresh_training(data):
    orders, _ = data
    _, _, te = F.split(orders)
    saved, fresh = DataCoShield.load(MODEL_DIR), DataCoShield().fit(orders)
    np.testing.assert_allclose(saved.model.predict_proba(saved.coder.transform(te)),
                               fresh.model.predict_proba(fresh.coder.transform(te)))


def test_debit_order_is_confirmed_with_tracking_id(desk):
    b = desk.create(RETURNING | {"payment_type": "DEBIT"})
    assert b.decision["action"] == "ALLOW" and b.status == "CONFIRMED"
    assert re.fullmatch(r"FS180201[A-Z0-9]{8}", b.tracking_id)
    assert b.label["ship_to"] == "San Salvador, El Salvador" and b.label["items"] == 4


def test_transfer_order_held_then_reviewed(desk):
    b1 = desk.create(RETURNING | {"payment_type": "TRANSFER"})
    b2 = desk.create(RETURNING | {"payment_type": "TRANSFER"})
    assert b1.status == b2.status == "UNDER_REVIEW"
    assert {b.booking_id for b in desk.queue()} == {b1.booking_id, b2.booking_id}
    assert desk.review(b1.booking_id, approve=False, note="no transfer received").status == "BLOCKED"
    assert b1.reference.startswith("REF-") and b1.tracking_id is None
    assert desk.review(b2.booking_id, approve=True).status == "CONFIRMED" and b2.tracking_id
    assert desk.queue() == []
    with pytest.raises(BookingError):
        desk.review(b1.booking_id, approve=True)


def test_step_up_right_code_confirms(desk):
    b = desk.create(RISKY)
    assert b.decision["action"] == "STEP_UP" and b.status == "VERIFICATION_REQUIRED"
    desk.verify(b.booking_id, "not-the-code")
    assert b.status == "VERIFICATION_REQUIRED" and b.attempts_left == 2
    desk.verify(b.booking_id, b.verification_code)
    assert b.status == "CONFIRMED" and b.tracking_id and b.verification_code is None


def test_step_up_three_wrong_codes_block(desk):
    b = desk.create(RISKY)
    for _ in range(3):
        desk.verify(b.booking_id, "000000" if b.verification_code != "000000" else "111111")
    assert b.status == "BLOCKED" and b.reference
    with pytest.raises(BookingError):
        desk.verify(b.booking_id, "123456")


def test_new_customer_gets_new_id_and_history(desk):
    form = dict(customer_segment="Consumer", customer_country="Puerto Rico", customer_city="Caguas", payment_type="DEBIT",
                shipping_mode="Same Day", order_country="Francia", order_city="Paris",
                items=[dict(product_id=1004, quantity=2, discount_rate=0.2)])
    b1 = desk.create(form)
    desk.now = lambda: FIXED_NOW + pd.Timedelta(hours=1)
    b2 = desk.create(form | {"customer_id": b1.customer_id})
    assert b1.customer_id > 20757 and b2.customer_id == b1.customer_id
    assert desk.customer(b1.customer_id)["earlier_orders"] == 2
    seen = desk.shield.ledger.get(b2.booking_id)["features"]
    assert seen["cust_n_prior"] == 1 and seen["cust_orders_7d"] == 1   # the first booking is now history


@pytest.mark.parametrize("change, message", [
    ({"order_country": "Atlantis"}, "not one we ship to"),
    ({"customer_id": 999999}, "not known"),
    ({"shipping_mode": "Teleport"}, "Shipping mode"),
    ({"items": []}, "at least one item"),
    ({"items": [dict(product_id=957, quantity=9, discount_rate=0)]}, "between 1 and 5"),
    ({"items": [dict(product_id=957, quantity=1, discount_rate=0.5)]}, "Discount"),
])
def test_bad_input_is_rejected(desk, change, message):
    with pytest.raises(BookingError, match=message):
        desk.create(RETURNING | {"payment_type": "DEBIT"} | change)


def test_every_state_change_is_in_the_ledger(desk):
    b = desk.create(RISKY)
    desk.verify(b.booking_id, b.verification_code)
    ok, n = desk.shield.ledger.verify()
    assert ok and n == 3          # the model decision + the final decision (with rules) + the confirmation
