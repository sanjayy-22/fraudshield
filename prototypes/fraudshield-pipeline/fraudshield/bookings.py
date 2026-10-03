"""Booking desk: turns a DataCoShield decision into what the customer and the analyst see.

A booking moves through these states:

    ALLOW   → CONFIRMED              tracking ID + shipping label issued at once
    STEP_UP → VERIFICATION_REQUIRED  customer enters a one-time code
                → CONFIRMED (right code) or BLOCKED (3 wrong codes)
    HOLD    → UNDER_REVIEW           waits in the analyst queue
                → CONFIRMED (approved) or BLOCKED (rejected)
    BLOCK   → BLOCKED                reference number only, no shipment

The fraud model only sees booking-time fields. Every decision and every later state change is
appended to the hash-chained ledger.

Demo-only simplifications, stated so nobody mistakes them for production behaviour:
* There is no SMS or e-mail gateway. The one-time code is returned in the API response
  (`demo_verification_code`) so the person testing can type it in.
* Bookings live in memory and are lost when the server restarts; the ledger file keeps the record.
* The clock is a "dataset clock" that starts on 2018-02-01 09:00 (the day after DataCo ends) and
  runs in real time, so customer history features stay in the range the model was trained on.
"""
from __future__ import annotations

import secrets
import string
import time
from dataclasses import dataclass, field

import pandas as pd

from .dataco import DataCoShield

CLOCK_START = pd.Timestamp("2018-02-01 09:00")
SCHEDULED_DAYS = {"Same Day": 0, "First Class": 1, "Second Class": 2, "Standard Class": 4}
PAYMENT_TYPES = ["DEBIT", "TRANSFER", "PAYMENT", "CASH"]
SEGMENTS = ["Consumer", "Corporate", "Home Office"]
MAX_CODE_ATTEMPTS = 3

STATUS_FOR_ACTION = {"ALLOW": "CONFIRMED", "STEP_UP": "VERIFICATION_REQUIRED", "HOLD": "UNDER_REVIEW",
                     "BLOCK": "BLOCKED"}
MESSAGES = {
    "CONFIRMED": "Booking confirmed. Your tracking ID and shipping label are ready.",
    "VERIFICATION_REQUIRED": "We need to confirm it's you. Enter the 6-digit code we sent to the customer's phone.",
    "UNDER_REVIEW": "Your booking is being checked by our team. You'll get a tracking ID once it's approved.",
    "BLOCKED": "We couldn't accept this booking. Quote the reference number if you contact support.",
}


class BookingError(ValueError):
    """A request the desk cannot carry out; the message is safe to show to the user."""


@dataclass
class Booking:
    booking_id: str
    order_id: int
    created_at: str
    customer_id: int
    status: str
    decision: dict
    p_fraud: float
    reasons: list
    rule_text: list
    conformal: dict
    order: dict
    items: list
    tracking_id: str | None = None
    label: dict | None = None
    reference: str | None = None
    verification_code: str | None = None
    attempts_left: int = 0
    events: list = field(default_factory=list)

    def public(self, include_code: bool = False) -> dict:
        out = {k: v for k, v in self.__dict__.items() if k not in ("verification_code", "order")}
        out["message"] = MESSAGES[self.status]
        out["summary"] = {k: self.order[k] for k in ("payment_type", "shipping_mode", "order_country", "order_city",
                                                       "net_total", "n_units")}
        if include_code and self.status == "VERIFICATION_REQUIRED":
            out["demo_verification_code"] = self.verification_code
            out["demo_note"] = "No SMS gateway in this demo: the code is shown here instead of being sent."
        return out


def _code(n: int, alphabet: str) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(n))


class BookingDesk:
    def __init__(self, shield: DataCoShield, orders: pd.DataFrame, items: pd.DataFrame):
        self.shield = shield
        self.started = time.time()
        self.bookings: dict[str, Booking] = {}
        self.next_order_id = int(orders.order_id.max()) + 1
        self.next_customer_id = int(orders.customer_id.max()) + 1
        # live history: by the dataset clock every DataCo order is in the past
        shield.known = orders.copy()
        self._build_reference(orders, items)

    # ------------------------------------------------------------------ reference data for the form
    def _build_reference(self, orders: pd.DataFrame, items: pd.DataFrame) -> None:
        geo = orders.groupby("order_country").agg(region=("order_region", lambda s: s.mode().iat[0]),
                                                  market=("market", lambda s: s.mode().iat[0]),
                                                  n=("order_id", "size"))
        self.geo = geo
        top_cities = (orders.groupby(["order_country", "order_city"]).size().rename("n").reset_index()
                      .sort_values("n", ascending=False).groupby("order_country").head(25))
        self.cities = {c: sorted(g.order_city) for c, g in top_cities.groupby("order_country")}
        prod = items.groupby("product_card_id").agg(
            name=("product_name", "first"), category=("category_name", "first"),
            department=("department_name", "first"), price=("product_price", "first"),
            profit_ratio=("order_item_profit_ratio", "median"), popularity=("order_id", "size"))
        self.products = prod.sort_values("popularity", ascending=False)
        last = orders.sort_values("ts").groupby("customer_id").tail(1).set_index("customer_id")
        self.customers = last[["customer_segment", "customer_country", "customer_city"]]
        self.customer_orders = orders.groupby("customer_id").size()

    def options(self) -> dict:
        return dict(
            payment_types=PAYMENT_TYPES, shipping_modes=list(SCHEDULED_DAYS), scheduled_days=SCHEDULED_DAYS,
            segments=SEGMENTS, customer_countries=sorted(self.customers.customer_country.unique()),
            countries=[dict(country=c, region=r.region, market=r.market)
                       for c, r in self.geo.sort_values("n", ascending=False).iterrows()],
            cities=self.cities,
            products=[dict(id=int(i), name=r["name"], category=r.category, department=r.department,
                           price=round(float(r.price), 2)) for i, r in self.products.iterrows()],
            clock=str(self.now()),
        )

    def customer(self, customer_id: int) -> dict | None:
        if customer_id not in self.customers.index:
            return None
        r = self.customers.loc[customer_id]
        return dict(customer_id=customer_id, segment=r.customer_segment, country=r.customer_country,
                    city=r.customer_city, earlier_orders=int(self.customer_orders.get(customer_id, 0)))

    def now(self) -> pd.Timestamp:
        return (CLOCK_START + pd.Timedelta(seconds=time.time() - self.started)).floor("s")

    # ------------------------------------------------------------------ create
    def _order_from_form(self, form: dict) -> tuple[dict, list[dict], list[dict]]:
        from dataco_features import order_from_items   # prototypes/data is on sys.path via fraudshield.dataco

        cid = int(form.get("customer_id") or 0)
        cust = self.customer(cid) if cid else None
        if cid and cust is None:
            raise BookingError(f"Customer {cid} is not known. Leave the ID empty to book as a new customer.")
        if cust is None:
            cid = self.next_customer_id
            self.next_customer_id += 1
            segment, ccountry, ccity = form.get("customer_segment"), form.get("customer_country"), form.get("customer_city")
            if not (segment and ccountry and ccity):
                raise BookingError("A new customer needs a segment, country and city.")
            # register the customer so the next booking can use this ID
            self.customers.loc[cid] = [segment, ccountry, ccity]
        else:
            segment, ccountry, ccity = cust["segment"], cust["country"], cust["city"]

        country = form.get("order_country")
        if country not in self.geo.index:
            raise BookingError(f"Destination country '{country}' is not one we ship to. Pick one from the list.")
        city = (form.get("order_city") or "").strip()
        if not city:
            raise BookingError("Enter the destination city.")
        mode = form.get("shipping_mode")
        if mode not in SCHEDULED_DAYS:
            raise BookingError(f"Shipping mode must be one of {', '.join(SCHEDULED_DAYS)}.")
        if form.get("payment_type") not in PAYMENT_TYPES:
            raise BookingError(f"Payment type must be one of {', '.join(PAYMENT_TYPES)}.")
        lines = form.get("items") or []
        if not lines:
            raise BookingError("Add at least one item.")
        if len(lines) > 5:
            raise BookingError("An order can have at most 5 lines (the most DataCo ever saw).")

        raw, shown = [], []
        for ln in lines:
            pid = int(ln["product_id"])
            if pid not in self.products.index:
                raise BookingError(f"Unknown product {pid}.")
            qty, rate = int(ln["quantity"]), float(ln.get("discount_rate", 0))
            if not 1 <= qty <= 5:
                raise BookingError("Quantity per line must be between 1 and 5.")
            if not 0 <= rate <= 0.25:
                raise BookingError("Discount rate must be between 0 and 25%.")
            p = self.products.loc[pid]
            sales = qty * float(p.price)
            discount = round(sales * rate, 2)
            net = sales - discount
            raw.append(dict(quantity=qty, unit_price=float(p.price), discount=discount, discount_rate=rate,
                            profit=round(net * float(p.profit_ratio), 2), profit_ratio=float(p.profit_ratio),
                            category=p.category, department=p.department, product_id=pid))
            shown.append(dict(product_id=pid, name=p["name"], quantity=qty, unit_price=round(float(p.price), 2),
                              discount_rate=rate, line_total=round(net, 2)))

        g = self.geo.loc[country]
        header = dict(order_id=self.next_order_id, ts=self.now(), customer_id=cid, payment_type=form["payment_type"],
                      shipping_mode=mode, days_shipment_scheduled=SCHEDULED_DAYS[mode], market=g.market,
                      order_region=g.region, order_country=country, order_city=city, customer_segment=segment,
                      customer_country=ccountry, customer_city=ccity)
        self.next_order_id += 1
        return order_from_items(header, raw), raw, shown

    def create(self, form: dict) -> Booking:
        order, _, shown = self._order_from_form(form)
        cid = order["customer_id"]
        self.customer_orders.loc[cid] = int(self.customer_orders.get(cid, 0)) + 1
        r = self.shield.score_new(order, explain=True)
        action = r["decision"]["action"]
        b = Booking(booking_id=r["booking_id"], order_id=order["order_id"], created_at=str(order["ts"]),
                    customer_id=order["customer_id"], status=STATUS_FOR_ACTION[action], decision=r["decision"],
                    p_fraud=round(r["p_fraud"], 4), reasons=r.get("reasons", []), rule_text=r.get("rule_text", []),
                    conformal=r["conformal"], order=order, items=shown)
        b.events.append(dict(at=b.created_at, status=b.status, note=f"model decision: {action}"))
        if b.status == "CONFIRMED":
            self._confirm(b, "approved automatically")
        elif b.status == "VERIFICATION_REQUIRED":
            b.verification_code = _code(6, string.digits)
            b.attempts_left = MAX_CODE_ATTEMPTS
        elif b.status == "BLOCKED":
            self._block(b, "blocked by the decision policy")
        self.bookings[b.booking_id] = b
        return b

    # ------------------------------------------------------------------ transitions
    def _event(self, b: Booking, status: str, note: str) -> None:
        b.status = status
        at = str(self.now())
        b.events.append(dict(at=at, status=status, note=note))
        if self.shield.ledger is not None:
            self.shield.ledger.append(dict(booking_id=b.booking_id, event=note, status=status, ts=at,
                                           tracking_id=b.tracking_id, reference=b.reference))

    def _confirm(self, b: Booking, note: str) -> None:
        b.tracking_id = f"FS{self.now():%y%m%d}{_code(8, string.ascii_uppercase + string.digits)}"
        o = b.order
        b.label = dict(tracking_id=b.tracking_id, service=o["shipping_mode"],
                       scheduled_days=int(o["days_shipment_scheduled"]),
                       ship_to=f"{o['order_city']}, {o['order_country']}", region=o["order_region"],
                       customer_id=b.customer_id, items=sum(i["quantity"] for i in b.items),
                       declared_value_usd=round(float(o["net_total"]), 2), booked_at=b.created_at)
        b.verification_code = None
        self._event(b, "CONFIRMED", note)

    def _block(self, b: Booking, note: str) -> None:
        b.reference = f"REF-{_code(8, string.ascii_uppercase + string.digits)}"
        b.verification_code = None
        self._event(b, "BLOCKED", note)

    def get(self, booking_id: str) -> Booking:
        b = self.bookings.get(booking_id)
        if b is None:
            raise KeyError(booking_id)
        return b

    def verify(self, booking_id: str, code: str) -> Booking:
        b = self.get(booking_id)
        if b.status != "VERIFICATION_REQUIRED":
            raise BookingError(f"This booking is {b.status.replace('_', ' ').lower()}; there is nothing to verify.")
        if secrets.compare_digest(str(code).strip(), b.verification_code or ""):
            self._confirm(b, "customer passed verification")
        else:
            b.attempts_left -= 1
            if b.attempts_left <= 0:
                self._block(b, "verification failed 3 times")
            else:
                b.events.append(dict(at=str(self.now()), status=b.status,
                                     note=f"wrong code, {b.attempts_left} attempt(s) left"))
        return b

    def review(self, booking_id: str, approve: bool, note: str = "") -> Booking:
        b = self.get(booking_id)
        if b.status != "UNDER_REVIEW":
            raise BookingError(f"This booking is {b.status.replace('_', ' ').lower()}; only bookings under review can be reviewed.")
        suffix = f": {note}" if note else ""
        if approve:
            self._confirm(b, "analyst approved" + suffix)
        else:
            self._block(b, "analyst rejected" + suffix)
        return b

    def queue(self) -> list[Booking]:
        return [b for b in self.bookings.values() if b.status == "UNDER_REVIEW"]
