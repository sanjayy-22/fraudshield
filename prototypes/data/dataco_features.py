"""Booking-time feature contract + point-in-time features for the real DataCo data.

`cleaned_dataco.csv` is one row per order *item*. FraudShield decides once per *order*, at the
moment it is placed, so this module

1. declares the role of every cleaned column (target / leak / identifier / booking-time),
2. rolls items up to one row per order using booking-time columns only,
3. adds point-in-time history features computed from strictly earlier orders, with
   labels (fraud / cancel) visible only after a delay, as in `featurize.py`'s online store,
4. provides the fixed time split shared by every DataCo experiment.

The contract is enforced by `assert_no_leak()`, which every experiment calls on its feature list
(except the deliberately leaky baseline e0, which uses `LEAKY_ORDER_COLS` explicitly).

Leakage audit of the cleaned CSV (see notes/comparison-dataco.md for the numbers):
* `order_status == SUSPECTED_FRAUD` *is* the label.
* `delivery_status` is 'Shipping canceled' for 100 % of fraud rows, and `late_delivery_risk` / `is_late` are 0
  for 100 % of them. Both are recorded after the order is stopped.
* `days_shipping_real`, `shipping_date` and `shipping_delay_days` only exist once the parcel has shipped.
* `payment_type` partitions `order_status` exactly (CASH = CLOSED, DEBIT = COMPLETE/ON_HOLD,
  PAYMENT = PENDING_PAYMENT/PAYMENT_REVIEW, TRANSFER = PENDING/PROCESSING/CANCELED/SUSPECTED_FRAUD).
  It is plausibly known at booking, but it looks generated from the status. It is therefore kept in a
  separate group so that every result can be reported with and without it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA_PATH = Path(__file__).resolve().parent / "cleaned_dataco.csv"

TARGET = "is_fraud"

# ------------------------------------------------------------------ column roles (item-level CSV)
LEAK_COLS = [            # outcome / post-booking information: never a model input
    "order_status", "delivery_status", "late_delivery_risk", "is_late",
    "days_shipping_real", "shipping_date", "shipping_delay_days",
]
ID_PII_COLS = [          # identifiers and names: never a model input
    "customer_fname", "customer_lname", "customer_id", "order_id", "order_item_id",
    "order_item_cardprod_id", "product_name", "customer_zipcode", "latitude", "longitude",
]
STATUS_DERIVED_COLS = ["payment_type"]   # see module docstring

# ------------------------------------------------------------------ order-level feature groups
CAT_COLS = ["shipping_mode", "market", "order_region", "customer_segment", "customer_country",
            "main_department", "main_category"]
BASE_NUM_COLS = [
    "days_shipment_scheduled", "n_items", "n_units", "n_categories", "n_departments",
    "gross_sales", "net_total", "discount_total", "discount_rate_max", "discount_rate_mean",
    "profit_total", "profit_ratio_mean", "max_unit_price", "order_hour", "order_weekday", "order_day",
]
HISTORY_COLS = [         # point-in-time, strictly earlier orders; labels delayed by LABEL_DELAY
    "cust_n_prior", "cust_days_since_last", "cust_prior_spend", "cust_spend_ratio",
    "cust_orders_7d", "cust_orders_30d", "cust_prior_transfer", "cust_prior_fraud",
    "cust_prior_cancel", "cust_new_country", "cust_new_city",
]
ENTITY_COLS = [          # entity-graph counters (experiment e3)
    "city_orders_7d", "city_fraud_30d", "city_fraud_rate_90d",
    "product_fraud_30d", "product_fraud_rate_90d", "custcity_fraud_90d",
]
PAYMENT_COLS = ["is_transfer"]

LEAKY_ORDER_COLS = ["leak_canceled", "leak_late_risk", "leak_days_real", "leak_delay_minus_sched"]

LABEL_DELAY = pd.Timedelta(days=1)   # a fraud / cancel outcome becomes visible one day after the order

SPLITS = {   # fixed, time-ordered; never shuffled
    "train": ("2015-01-01", "2017-01-01"),
    "valid": ("2017-01-01", "2017-07-01"),
    "test": ("2017-07-01", "2018-02-01"),
}


def honest_features(include_payment: bool = True, include_entity: bool = False) -> list[str]:
    cols = BASE_NUM_COLS + CAT_COLS + HISTORY_COLS
    if include_entity:
        cols = cols + ENTITY_COLS
    if include_payment:
        cols = cols + PAYMENT_COLS
    return cols


def assert_no_leak(cols: list[str]) -> None:
    banned = set(LEAK_COLS) | set(ID_PII_COLS) | set(LEAKY_ORDER_COLS) | {TARGET}
    bad = sorted(set(cols) & banned)
    if bad:
        raise ValueError(f"leaking / identifier columns in feature list: {bad}")


# ------------------------------------------------------------------ loading + order roll-up
def load_items(path: str | Path = DATA_PATH) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["order_date", "shipping_date"])


def _main_by_value(items: pd.DataFrame, col: str) -> pd.Series:
    """Value of `col` on the order's highest-value item."""
    idx = items.groupby("order_id")["order_item_total"].idxmax()
    return items.loc[idx].set_index("order_id")[col]


def to_orders(items: pd.DataFrame) -> pd.DataFrame:
    g = items.groupby("order_id", sort=False)
    o = g.agg(
        ts=("order_date", "first"), customer_id=("customer_id", "first"), is_fraud=("is_fraud", "max"),  # constant within an order
        payment_type=("payment_type", "first"), shipping_mode=("shipping_mode", "first"),
        days_shipment_scheduled=("days_shipment_scheduled", "first"), market=("market", "first"),
        order_region=("order_region", "first"), order_country=("order_country", "first"),
        order_city=("order_city", "first"), customer_segment=("customer_segment", "first"),
        customer_country=("customer_country", "first"), customer_city=("customer_city", "first"),
        n_items=("order_item_id", "size"), n_units=("order_item_quantity", "sum"),
        n_categories=("category_id", "nunique"), n_departments=("department_id", "nunique"),
        gross_sales=("sales", "sum"), net_total=("order_item_total", "sum"),
        discount_total=("order_item_discount", "sum"), discount_rate_max=("order_item_discount_rate", "max"),
        discount_rate_mean=("order_item_discount_rate", "mean"), profit_total=("order_profit_per_order", "sum"),
        profit_ratio_mean=("order_item_profit_ratio", "mean"), max_unit_price=("order_item_product_price", "max"),
        # leak columns, kept only for the leaky baseline and for the audit
        order_status=("order_status", "first"), delivery_status=("delivery_status", "first"),
        late_delivery_risk=("late_delivery_risk", "max"), days_shipping_real=("days_shipping_real", "first"),
    )
    o["main_department"] = _main_by_value(items, "department_name").reindex(o.index)
    o["main_category"] = _main_by_value(items, "category_name").reindex(o.index)
    o["main_product"] = _main_by_value(items, "product_card_id").reindex(o.index)
    o = o.reset_index().sort_values(["ts", "order_id"], kind="stable").reset_index(drop=True)

    o["order_hour"] = o.ts.dt.hour
    o["order_weekday"] = o.ts.dt.weekday
    o["order_day"] = o.ts.dt.day
    o["is_transfer"] = (o.payment_type == "TRANSFER").astype(int)
    o["is_cancel"] = (o.order_status == "CANCELED").astype(int)
    o["leak_canceled"] = (o.delivery_status == "Shipping canceled").astype(int)
    o["leak_late_risk"] = o.late_delivery_risk
    o["leak_days_real"] = o.days_shipping_real
    o["leak_delay_minus_sched"] = o.days_shipping_real - o.days_shipment_scheduled
    return o


# ------------------------------------------------------------------ point-in-time helpers
def _cum_at(o: pd.DataFrame, key: str, cut: pd.Series, value: str | None) -> np.ndarray:
    """For each row i: sum of `value` (or count) over rows with the same `key` and ts <= cut[i]."""
    right = o[[key, "ts"]].copy()
    right["ts"] = right["ts"].astype("datetime64[ns]")
    right["_v"] = 1.0 if value is None else o[value].astype(float)
    right = right.sort_values("ts", kind="stable")
    right["_cum"] = right.groupby(key)["_v"].cumsum()
    left = pd.DataFrame({key: o[key].values, "_cut": cut.astype("datetime64[ns]").values, "_row": np.arange(len(o))})
    left = left.sort_values("_cut", kind="stable")
    m = pd.merge_asof(left, right[[key, "ts", "_cum"]], left_on="_cut", right_on="ts", by=key,
                      direction="backward", allow_exact_matches=True)
    out = np.zeros(len(o))
    out[m["_row"].values] = m["_cum"].fillna(0.0).values
    return out


def _window(o: pd.DataFrame, key: str, window: pd.Timedelta | None, value: str | None = None,
            delay: pd.Timedelta = pd.Timedelta(0)) -> np.ndarray:
    """Sum of `value` over earlier rows with the same key in [ts - delay - window, ts - delay).
    The upper edge is exclusive (ts - 1 s when delay is 0), so orders placed in the same minute are never counted."""
    eps = pd.Timedelta(seconds=1)
    hi = _cum_at(o, key, o.ts - delay - eps, value)
    if window is None:
        return hi
    lo = _cum_at(o, key, o.ts - delay - window - eps, value)
    return hi - lo


def _first_seen(o: pd.DataFrame, cust: str, attr: str) -> np.ndarray:
    """1 if this customer has never ordered with this attribute value before."""
    pair = o[cust].astype(str) + "|" + o[attr].astype(str)
    return (~pair.duplicated()).astype(int).values   # rows are sorted by ts


def add_history(o: pd.DataFrame) -> pd.DataFrame:
    o = o.copy()
    c = "customer_id"
    o["cust_n_prior"] = _window(o, c, None)
    prev_ts = o.groupby(c)["ts"].shift(1)
    o["cust_days_since_last"] = ((o.ts - prev_ts).dt.total_seconds() / 86400).fillna(-1.0)
    o["cust_prior_spend"] = _window(o, c, None, "net_total")
    mean_prior = o.cust_prior_spend / o.cust_n_prior.replace(0, np.nan)
    o["cust_spend_ratio"] = (o.net_total / mean_prior).fillna(-1.0)
    o["cust_orders_7d"] = _window(o, c, pd.Timedelta(days=7))
    o["cust_orders_30d"] = _window(o, c, pd.Timedelta(days=30))
    o["cust_prior_transfer"] = _window(o, c, None, "is_transfer")
    o["cust_prior_fraud"] = _window(o, c, None, "is_fraud", delay=LABEL_DELAY)
    o["cust_prior_cancel"] = _window(o, c, None, "is_cancel", delay=LABEL_DELAY)
    o["cust_new_country"] = _first_seen(o, c, "order_country")
    o["cust_new_city"] = _first_seen(o, c, "order_city")
    return o


def add_entity(o: pd.DataFrame) -> pd.DataFrame:
    """Entity-graph counters: the order links customer ↔ destination city ↔ product.
    Fraud counts propagate along those links with the label delay."""
    o = o.copy()
    d7, d30, d90 = (pd.Timedelta(days=d) for d in (7, 30, 90))
    o["city_orders_7d"] = _window(o, "order_city", d7)
    o["city_fraud_30d"] = _window(o, "order_city", d30, "is_fraud", delay=LABEL_DELAY)
    n90 = _window(o, "order_city", d90, delay=LABEL_DELAY)
    o["city_fraud_rate_90d"] = (_window(o, "order_city", d90, "is_fraud", delay=LABEL_DELAY) + 0.08) / (n90 + 1)
    o["product_fraud_30d"] = _window(o, "main_product", d30, "is_fraud", delay=LABEL_DELAY)
    p90 = _window(o, "main_product", d90, delay=LABEL_DELAY)
    o["product_fraud_rate_90d"] = (_window(o, "main_product", d90, "is_fraud", delay=LABEL_DELAY) + 0.08) / (p90 + 1)
    # fraud on orders from the same customer *home* city (shared-address proxy) in the last 90 days
    o["custcity_fraud_90d"] = _window(o, "customer_city", d90, "is_fraud", delay=LABEL_DELAY)
    return o


# ------------------------------------------------------------------ live path: one new order at a time
ORDER_HEADER = ["order_id", "ts", "customer_id", "payment_type", "shipping_mode", "days_shipment_scheduled", "market",
                "order_region", "order_country", "order_city", "customer_segment", "customer_country", "customer_city"]
ITEM_FIELDS = ["quantity", "unit_price", "discount", "discount_rate", "profit", "profit_ratio", "category",
               "department", "product_id"]


def order_from_items(header: dict, items: list[dict]) -> dict:
    """Booking-time order row from a raw order (header + items), matching `to_orders()` aggregation.
    Item amounts are taken as given, because DataCo's discount and profit are not exactly rate × amount."""
    it = pd.DataFrame(items)
    sales = it.quantity * it.unit_price
    net = sales - it.discount
    main = int(np.argmax(net.values))
    ts = pd.Timestamp(header["ts"])
    row = {k: header[k] for k in ORDER_HEADER if k in header}
    row.update(
        ts=ts, n_items=len(it), n_units=float(it.quantity.sum()), n_categories=it.category.nunique(),
        n_departments=it.department.nunique(), gross_sales=float(sales.sum()), net_total=float(net.sum()),
        discount_total=float(it.discount.sum()), discount_rate_max=float(it.discount_rate.max()),
        discount_rate_mean=float(it.discount_rate.mean()), profit_total=float(it.profit.sum()),
        profit_ratio_mean=float(it.profit_ratio.mean()), max_unit_price=float(it.unit_price.max()),
        main_department=it.department.iloc[main], main_category=it.category.iloc[main],
        main_product=it.product_id.iloc[main] if "product_id" in it else -1,
        order_hour=ts.hour, order_weekday=ts.weekday(), order_day=ts.day,
        is_transfer=int(header["payment_type"] == "TRANSFER"),
    )
    return row


_HIST_INPUT = ["customer_id", "ts", "net_total", "is_transfer", "is_fraud", "is_cancel", "order_country", "order_city"]


def history_for(known: pd.DataFrame, order: dict) -> dict:
    """Point-in-time history features for one new order, given the orders already known.
    Runs the batch `add_history()` on the customer's earlier orders + this one, so live and batch
    features are computed by the same code. The new order's own outcome is unknown (set to 0) and
    can never reach its features, because every history window ends strictly before `ts`."""
    ts = pd.Timestamp(order["ts"])
    prior = known[(known.customer_id == order["customer_id"]) & (known.ts < ts)][_HIST_INPUT]
    new = pd.DataFrame([{**{c: order.get(c) for c in _HIST_INPUT}, "ts": ts, "is_fraud": 0, "is_cancel": 0}])
    frame = pd.concat([prior, new], ignore_index=True)
    frame["ts"] = frame.ts.astype("datetime64[ns]")
    frame = frame.sort_values("ts", kind="stable").reset_index(drop=True)
    return {c: float(v) for c, v in add_history(frame).iloc[-1][HISTORY_COLS].items()}


def build_orders(path: str | Path = DATA_PATH, entity: bool = True) -> pd.DataFrame:
    o = add_history(to_orders(load_items(path)))
    if entity:
        o = add_entity(o)
    o["split"] = "none"
    for name, (a, b) in SPLITS.items():
        o.loc[(o.ts >= a) & (o.ts < b), "split"] = name
    return o


def matrix(o: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Model matrix: categoricals become pandas `category` (LightGBM handles them natively)."""
    X = o[cols].copy()
    for c in cols:
        if c in CAT_COLS:
            X[c] = X[c].astype("category")
    return X


def split(o: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return o[o.split == "train"], o[o.split == "valid"], o[o.split == "test"]


_CACHE = Path(__file__).resolve().parent / "dataco_orders.pkl"


def cached_orders() -> pd.DataFrame:
    """build_orders() with an on-disk cache (git-ignored), rebuilt when this file or the CSV is newer."""
    src = max(DATA_PATH.stat().st_mtime, Path(__file__).stat().st_mtime)
    if _CACHE.exists() and _CACHE.stat().st_mtime >= src:
        return pd.read_pickle(_CACHE)
    o = build_orders()
    o.to_pickle(_CACHE)
    return o


if __name__ == "__main__":
    o = build_orders()
    print(o.shape)
    print(o.groupby("split").agg(orders=("is_fraud", "size"), fraud=("is_fraud", "sum")))
    print(o[HISTORY_COLS + ENTITY_COLS].describe().T[["mean", "min", "max"]])
