"""Point-in-time online feature store for FraudShield.

One object consumes the booking stream in event order. For every booking it first
computes features using ONLY what was known before that booking (behavioural
profile of the shipper, cohort priors, velocity windows, entity-graph counters,
delayed fraud labels), then absorbs the booking.

The same class is used offline (to build training sets — no train/serve skew) and
online (in the pipeline prototype). In production the state below maps 1:1 onto a
Redis/Feast online store: per-shipper hashes, sliding-window counters, and
entity→accounts sets; the union-find is a degree-capped connected-component index.

Feature families
- behavioural novelty vs the shipper's OWN history, with Bayesian back-off to the
  shipper's cohort when history is thin (cold start)
- velocity (1h / 24h / 7d counts vs the shipper's baseline daily rate)
- identity/account: new device, new payment instrument, payment-instrument age,
  account age, dormancy
- entity graph: fan-in of the destination address / device / payment instrument
  across OTHER shippers, confirmed-fraud counts on each entity (labels arrive with
  a delay), and the fraud density of the connected component
- an unsupervised composite `drift_score` (used stand-alone in experiment C and as
  a feature elsewhere)
"""
from __future__ import annotations

import heapq
import math
from collections import Counter, defaultdict, deque

import numpy as np
import pandas as pd

ALPHA_CAT = 3.0          # pseudo-count weight of the cohort prior for categoricals
ALPHA_HOUR = 6.0         # ... for the hour-of-day histogram
SHRINK_K = 5.0           # pseudo-observations for Gaussian shrinkage to cohort
HUB_DEGREE = {"addr": 6, "dev": 10, "pay": 10}   # entities used by more shippers than this never bridge components
FANIN_WINDOW_DAYS = 30
LABEL_DELAY_DAYS = 10    # fraud is confirmed ~10 days after booking (post-delivery)
ESTABLISHED_DAYS = 7     # entities a shipper used >7 days before a fraud booking are the victim's own
COUNT_CAP = 3            # cumulative counts are capped so they cannot drift upward over months
COHORTS = ["individual", "sme", "ecommerce"]


class Welford:
    __slots__ = ("n", "mean", "m2")

    def __init__(self):
        self.n, self.mean, self.m2 = 0, 0.0, 0.0

    def add(self, x: float):
        self.n += 1
        d = x - self.mean
        self.mean += d / self.n
        self.m2 += d * (x - self.mean)

    @property
    def var(self) -> float:
        return self.m2 / (self.n - 1) if self.n > 1 else 0.0


class Profile:
    """Running behavioural profile of one shipper (or of one cohort)."""

    def __init__(self):
        self.n = 0
        self.first_t = None
        self.last_t = None
        self.dest_addr, self.dest_city, self.origin = Counter(), Counter(), Counter()
        self.service, self.contents = Counter(), Counter()
        self.hours = np.zeros(24)
        self.devices, self.payments = set(), set()
        self.first_use: dict[tuple, float] = {}   # (entity type, id) -> first time this shipper used it
        self.logw, self.logv = Welford(), Welford()
        self.recent = deque()          # event times (days) within the last 7 days

    def add(self, b: dict, t: float):
        self.n += 1
        self.first_t = t if self.first_t is None else self.first_t
        self.last_t = t
        self.dest_addr[b["dest_address_id"]] += 1
        self.dest_city[b["dest_city"]] += 1
        self.origin[b["origin_city"]] += 1
        self.service[b["service"]] += 1
        self.contents[b["contents"]] += 1
        self.hours[int(b["hour"]) % 24] += 1
        self.devices.add(b["device_id"])
        self.payments.add(b["payment_id"])
        for k in (("addr", b["dest_address_id"]), ("dev", b["device_id"]), ("pay", b["payment_id"])):
            self.first_use.setdefault(k, t)
        self.logw.add(math.log(max(b["weight_kg"], 0.01)))
        self.logv.add(math.log(max(b["declared_value"], 1.0)))
        self.recent.append(t)


class UnionFind:
    """Connected components over shipper and entity nodes, with per-component
    shipper count and confirmed-fraud count (merged on union)."""

    def __init__(self):
        self.parent, self.shippers, self.fraud = {}, {}, {}

    def add(self, x: str, shipper: bool = False):
        if x not in self.parent:
            self.parent[x] = x
            self.shippers[x] = 1 if shipper else 0
            self.fraud[x] = 0

    def find(self, x: str) -> str:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:          # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.shippers[ra] < self.shippers[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.shippers[ra] += self.shippers[rb]
        self.fraud[ra] += self.fraud[rb]

    def stats(self, x: str):
        if x not in self.parent:
            return 0, 0
        r = self.find(x)
        return self.shippers[r], self.fraud[r]


class OnlineFeatureStore:
    def __init__(self, cohort_backoff: bool = True, label_delay_days: float = LABEL_DELAY_DAYS):
        self.profiles: dict[str, Profile] = {}
        self.cohort: dict[str, Profile] = defaultdict(Profile)
        self.cohort_members: dict[str, set] = defaultdict(set)
        self.entity_users: dict[tuple, dict] = defaultdict(dict)   # (type,id) -> {sid: last_t}
        self.entity_fraud: Counter = Counter()
        self.uf = UnionFind()
        self.pending: list = []                                     # heap of (confirm_t, keys)
        self.cohort_backoff = cohort_backoff
        self.label_delay = label_delay_days
        self.t0: pd.Timestamp | None = None

    # ------------------------------------------------------------------ helpers
    def _t(self, ts) -> float:
        ts = pd.Timestamp(ts)
        if self.t0 is None:
            self.t0 = ts
        return (ts - self.t0).total_seconds() / 86400.0

    def _apply_due_labels(self, now: float):
        while self.pending and self.pending[0][0] <= now:
            _, keys = heapq.heappop(self.pending)
            roots = set()
            for k in keys:
                self.entity_fraud[k] += 1
                node = f"{k[0]}:{k[1]}"
                if node in self.uf.parent:
                    roots.add(self.uf.find(node))
            for r in roots:                     # one confirmed booking = +1 per component
                self.uf.fraud[r] += 1

    def _cat(self, cnt_s: Counter, n_s: int, cnt_c: Counter, n_c: int, key) -> tuple[float, float]:
        """(-log P(key | shipper) with cohort back-off, historical share for shipper)."""
        pc = (cnt_c[key] + 1.0) / (n_c + 20.0) if self.cohort_backoff else 0.05
        p = (cnt_s[key] + ALPHA_CAT * pc) / (n_s + ALPHA_CAT)
        return -math.log(p), (cnt_s[key] / n_s if n_s else 0.0)

    def _hour(self, p: Profile, c: Profile, h: int) -> tuple[float, float]:
        pc = (c.hours[h] + 1.0) / (c.n + 24.0) if self.cohort_backoff else 1 / 24
        ph = (p.hours[h] + ALPHA_HOUR * pc) / (p.n + ALPHA_HOUR)
        return -math.log(ph), (p.hours[h] / p.n if p.n else 0.0)

    def _z(self, x: float, ws: Welford, wc: Welford) -> float:
        n = ws.n
        if self.cohort_backoff and wc.n >= 2:
            mean = (n * ws.mean + SHRINK_K * wc.mean) / (n + SHRINK_K) if n else wc.mean
            var = (n * ws.var + SHRINK_K * wc.var) / (n + SHRINK_K) if n >= 2 else wc.var
        else:
            if n < 2:
                return 0.0
            mean, var = ws.mean, ws.var
        return (x - mean) / math.sqrt(max(var, 1e-3))

    def _entity(self, key: tuple, sid: str, t: float) -> tuple[int, int, int, int, int]:
        users = self.entity_users.get(key, {})
        others_30d = sum(1 for s, lt in users.items() if s != sid and t - lt <= FANIN_WINDOW_DAYS)
        others_all = sum(1 for s in users if s != sid)
        comp_sh, comp_fr = self.uf.stats(f"{key[0]}:{key[1]}")
        return others_30d, others_all, self.entity_fraud[key], comp_sh, comp_fr

    # ------------------------------------------------------------------ features
    def features(self, b: dict) -> dict:
        t = self._t(b["ts"])
        self._apply_due_labels(t)
        sid = b["shipper_id"]
        p = self.profiles.get(sid) or Profile()
        c = self.cohort[b["cohort"]]
        n = p.n

        # velocity window maintenance (7-day sliding window on this shipper)
        while p.recent and t - p.recent[0] > 7:
            p.recent.popleft()
        vel_1h = sum(1 for r in p.recent if t - r <= 1 / 24)
        vel_24h = sum(1 for r in p.recent if t - r <= 1)
        vel_7d = len(p.recent)
        days_active = max((t - p.first_t) if p.first_t is not None else 0.0, 1.0)
        n_cohort_shippers = max(len(self.cohort_members[b["cohort"]]), 1)
        cohort_rate = c.n / (n_cohort_shippers * max(t, 1.0))
        rate = (n / days_active) if n >= 3 else max(cohort_rate, 0.02)
        vel24_ratio = vel_24h / max(rate, 0.02)

        dest_addr_nov, dest_addr_share = self._cat(p.dest_addr, n, c.dest_addr, c.n, b["dest_address_id"])
        dest_city_nov, dest_city_share = self._cat(p.dest_city, n, c.dest_city, c.n, b["dest_city"])
        origin_nov, origin_share = self._cat(p.origin, n, c.origin, c.n, b["origin_city"])
        service_nov, service_share = self._cat(p.service, n, c.service, c.n, b["service"])
        contents_nov, contents_share = self._cat(p.contents, n, c.contents, c.n, b["contents"])
        hour_nov, hour_share = self._hour(p, c, int(b["hour"]) % 24)

        w_z = self._z(math.log(max(b["weight_kg"], 0.01)), p.logw, c.logw)
        val_z = self._z(math.log(max(b["declared_value"], 1.0)), p.logv, c.logv)

        new_device = int(b["device_id"] not in p.devices) if n else 1
        new_payment = int(b["payment_id"] not in p.payments) if n else 1
        days_since_last = (t - p.last_t) if p.last_t is not None else -1.0

        a30, aall, afr, acs, acf = self._entity(("addr", b["dest_address_id"]), sid, t)
        d30, dall, dfr, dcs, dcf = self._entity(("dev", b["device_id"]), sid, t)
        p30, pall, pfr, pcs, pcf = self._entity(("pay", b["payment_id"]), sid, t)
        scs, scf = self.uf.stats(f"s:{sid}")
        comp_sh = max(acs, dcs, pcs, scs)
        comp_fr = max(acf, dcf, pcf, scf)

        f = dict(
            booking_id=b.get("booking_id"), ts=b["ts"], shipper_id=sid, cohort=b["cohort"],
            is_fraud=int(b.get("is_fraud", 0)), scenario=b.get("scenario", ""),
            charge_inr=b["charge_inr"], declared_value=b["declared_value"], ltv=b["ltv"],
            # --- history / identity
            n_hist=n, log_n_hist=math.log1p(n), account_age_days=min(b["account_age_days"], 2000), days_since_last=min(days_since_last, 365),
            new_device=new_device, new_payment=new_payment,
            log_pay_age_min=math.log1p(max(b["pay_age_min"], 0.0)),
            # --- behavioural novelty vs own history (cohort back-off)
            dest_addr_seen=int(dest_addr_share > 0), dest_addr_nov=dest_addr_nov,
            dest_city_seen=int(dest_city_share > 0), dest_city_nov=dest_city_nov,
            origin_nov=origin_nov, origin_is_usual=int(origin_share >= 0.5),
            service_nov=service_nov, is_express=int(b["service"] != "ground"),
            contents_nov=contents_nov, hour=float(b["hour"]), hour_nov=hour_nov,
            w_z=w_z, val_z=val_z, log_weight=math.log(max(b["weight_kg"], 0.01)),
            log_value=math.log(max(b["declared_value"], 1.0)),
            # --- velocity
            vel_1h=vel_1h, vel_24h=vel_24h, vel_7d=vel_7d, vel24_ratio=vel24_ratio,
            # --- entity graph
            dest_fanin_30d=min(a30, 20), dest_fanin_all=min(aall, 50), dest_fraud=min(afr, COUNT_CAP),
            dev_shared_n=min(d30, 20), dev_fraud=min(dfr, COUNT_CAP), pay_shared_n=min(p30, 20), pay_fraud=min(pfr, COUNT_CAP),
            comp_shippers=min(comp_sh, 50), comp_fraud=min(comp_fr, COUNT_CAP),
            comp_fraud_ratio=min(comp_fr / max(comp_sh, 1), 3.0),
        )
        for ch in COHORTS:
            f[f"cohort_{ch}"] = int(b["cohort"] == ch)
        f["drift_score"] = drift_score(f)
        return f

    def update(self, b: dict, is_fraud: bool = False, absorb_profile: bool = True,
               label_delay: float | None = None):
        """Absorb a booking.

        absorb_profile=False keeps the booking OUT of the shipper's behavioural profile
        (quarantine) — used by the pipeline for bookings that were held/blocked and not yet
        verified, so a fraud burst cannot teach the profile that the mule address is
        'normal'. Entity-graph edges are always recorded.
        label_delay overrides the default confirmation delay (e.g. 1 day when a step-up
        verification or analyst review produced a fast label).
        """
        t = self._t(b["ts"])
        sid = b["shipper_id"]
        p = self.profiles.setdefault(sid, Profile())
        if absorb_profile:
            p.add(b, t)
            self.cohort[b["cohort"]].add(b, t)
        self.cohort_members[b["cohort"]].add(sid)
        keys = [("addr", b["dest_address_id"]), ("dev", b["device_id"]), ("pay", b["payment_id"])]
        snode = f"s:{sid}"
        self.uf.add(snode, shipper=True)
        for k in keys:
            self.entity_users[k][sid] = t
            node = f"{k[0]}:{k[1]}"
            self.uf.add(node)
            if len(self.entity_users[k]) <= HUB_DEGREE[k[0]]:     # super-node guard
                self.uf.union(snode, node)
        if is_fraud:
            # Burn only the infrastructure the fraudster brought. An entity this shipper had
            # already been using for more than ESTABLISHED_DAYS before the booking (their own
            # device, card, regular customer address) belongs to the victim, whose account gets
            # re-secured — it must not poison the victim's future legitimate bookings.
            flag = [k for k in keys if t - p.first_use.get(k, t) <= ESTABLISHED_DAYS] + [("s", sid)]
            delay = self.label_delay if label_delay is None else label_delay
            heapq.heappush(self.pending, (t + delay, flag))


def drift_score(f: dict) -> float:
    """Unsupervised behavioural-drift composite (experiment C). Hand-weighted, no labels."""
    return (0.35 * abs(f["w_z"]) + 0.15 * abs(f["val_z"])
            + 0.40 * f["dest_city_nov"] + 0.30 * f["dest_addr_nov"] + 0.30 * f["service_nov"]
            + 0.20 * f["contents_nov"] + 0.40 * f["hour_nov"] + 0.50 * f["origin_nov"]
            + 0.50 * math.log1p(f["vel24_ratio"])
            + 0.80 * f["new_device"] + 0.80 * f["new_payment"])


BEHAV_COLS = ["log_n_hist", "account_age_days", "days_since_last", "new_device", "new_payment",
              "log_pay_age_min", "dest_addr_seen", "dest_addr_nov", "dest_city_seen", "dest_city_nov",
              "origin_nov", "origin_is_usual", "service_nov", "is_express", "contents_nov", "hour",
              "hour_nov", "w_z", "val_z", "log_weight", "log_value", "vel_1h", "vel_24h", "vel_7d",
              "vel24_ratio", "cohort_individual", "cohort_sme", "cohort_ecommerce"]
GRAPH_COLS = ["dest_fanin_30d", "dest_fanin_all", "dest_fraud", "dev_shared_n", "dev_fraud",
              "pay_shared_n", "pay_fraud", "comp_shippers", "comp_fraud", "comp_fraud_ratio"]
FEATURE_COLS = BEHAV_COLS + GRAPH_COLS + ["drift_score"]
META_COLS = ["booking_id", "ts", "shipper_id", "cohort", "is_fraud", "scenario",
             "charge_inr", "declared_value", "ltv"]


def build_feature_frame(df: pd.DataFrame, cohort_backoff: bool = True,
                        store: OnlineFeatureStore | None = None) -> pd.DataFrame:
    """Replay the stream in time order; returns one feature row per booking."""
    store = store or OnlineFeatureStore(cohort_backoff=cohort_backoff)
    rows = []
    for b in df.sort_values("ts", kind="stable").to_dict("records"):
        rows.append(store.features(b))
        store.update(b, bool(b.get("is_fraud", 0)))
    out = pd.DataFrame(rows)
    return out


if __name__ == "__main__":
    import sys, time
    sys.path.insert(0, ".")
    from simulate import generate
    t = time.time()
    d = generate()
    X = build_feature_frame(d)
    print(f"{len(X)} rows, {len(FEATURE_COLS)} features, {time.time() - t:.1f}s")
    print(X.groupby("is_fraud")[["drift_score", "dest_fanin_30d", "comp_fraud", "w_z", "vel24_ratio"]].mean().round(2))
