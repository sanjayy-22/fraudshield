"""Leakage and point-in-time tests for the DataCo feature pipeline.

Run: python3 -m pytest tests/ -q   (needs prototypes/data/cleaned_dataco.csv)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prototypes" / "data"))
import dataco_features as F  # noqa: E402

pytestmark = pytest.mark.skipif(not F.DATA_PATH.exists(), reason="cleaned_dataco.csv not present")


@pytest.fixture(scope="module")
def items():
    return F.load_items()


@pytest.fixture(scope="module")
def orders():
    return F.cached_orders()


# ------------------------------------------------------------------ contract
@pytest.mark.parametrize("include_payment", [True, False])
@pytest.mark.parametrize("include_entity", [True, False])
def test_honest_feature_lists_pass_contract(include_payment, include_entity):
    F.assert_no_leak(F.honest_features(include_payment, include_entity))


@pytest.mark.parametrize("bad", F.LEAK_COLS + F.LEAKY_ORDER_COLS + ["customer_id", "order_id", F.TARGET])
def test_contract_rejects_leaks(bad):
    with pytest.raises(ValueError):
        F.assert_no_leak(F.honest_features() + [bad])


def test_every_item_column_has_a_role(items):
    """A new column in the cleaned CSV must be classified before it can be used."""
    used_raw = {"order_date", "customer_id", "is_fraud", "payment_type", "shipping_mode", "days_shipment_scheduled",
                "market", "order_region", "order_country", "order_city", "order_state", "customer_segment",
                "customer_country", "customer_city", "customer_state", "order_item_quantity", "category_id",
                "category_name", "department_id", "department_name", "sales", "order_item_total",
                "order_item_discount", "order_item_discount_rate", "order_profit_per_order", "benefit_per_order",
                "order_item_profit_ratio", "order_item_product_price", "product_price", "product_card_id", "order_hour"}
    roles = set(F.LEAK_COLS) | set(F.ID_PII_COLS) | set(F.STATUS_DERIVED_COLS) | used_raw
    assert set(items.columns) - roles == set()


# ------------------------------------------------------------------ grain + split
def test_label_constant_within_order(items):
    assert (items.groupby("order_id").is_fraud.nunique() == 1).all()


def test_one_row_per_order(orders, items):
    assert orders.order_id.is_unique
    assert len(orders) == items.order_id.nunique()


def test_splits_disjoint_and_time_ordered(orders):
    tr, va, te = F.split(orders)
    ids = [set(d.order_id) for d in (tr, va, te)]
    assert not (ids[0] & ids[1]) and not (ids[0] & ids[2]) and not (ids[1] & ids[2])
    assert tr.ts.max() < va.ts.min() and va.ts.max() < te.ts.min()
    assert (orders.split != "none").all()


# ------------------------------------------------------------------ point-in-time correctness
def test_history_matches_brute_force(orders):
    rng = np.random.default_rng(0)
    sample = orders.iloc[rng.choice(len(orders), 400, replace=False)]
    for _, r in sample.iterrows():
        prior = orders[(orders.customer_id == r.customer_id) & (orders.ts < r.ts)]
        assert r.cust_n_prior == len(prior)
        assert r.cust_prior_fraud == prior[prior.ts <= r.ts - F.LABEL_DELAY].is_fraud.sum()
        assert r.cust_orders_7d == (prior.ts >= r.ts - pd.Timedelta(days=7)).sum()
        assert np.isclose(r.cust_prior_spend, prior.net_total.sum())


def test_entity_counter_matches_brute_force(orders):
    rng = np.random.default_rng(1)
    sample = orders.iloc[rng.choice(len(orders), 200, replace=False)]
    for _, r in sample.iterrows():
        hi = r.ts - F.LABEL_DELAY
        win = orders[(orders.order_city == r.order_city) & (orders.ts < hi) & (orders.ts >= hi - pd.Timedelta(days=30))]
        assert r.city_fraud_30d == win.is_fraud.sum()


def test_future_labels_do_not_change_past_features(orders):
    """Flip every label from the test window onward; features before it must be identical."""
    base = orders.drop(columns=F.HISTORY_COLS + F.ENTITY_COLS + ["split"])
    flipped = base.copy()
    cut = pd.Timestamp(F.SPLITS["test"][0])
    late = flipped.ts >= cut
    flipped.loc[late, "is_fraud"] = 1 - flipped.loc[late, "is_fraud"]
    flipped.loc[late, "is_cancel"] = 1 - flipped.loc[late, "is_cancel"]
    a = F.add_entity(F.add_history(base))
    b = F.add_entity(F.add_history(flipped))
    early = (a.ts < cut).values
    cols = F.HISTORY_COLS + F.ENTITY_COLS
    pd.testing.assert_frame_equal(a.loc[early, cols].reset_index(drop=True), b.loc[early, cols].reset_index(drop=True))
