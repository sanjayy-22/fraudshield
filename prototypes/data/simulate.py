"""FraudShield synthetic booking-stream simulator.

Generates a time-ordered stream of shipment bookings for a population of shippers,
then injects account-takeover (ATO) fraud episodes organised into fraud rings that
share mule destination addresses, payment instruments and devices.

Design notes
- Everything is generated in *event time* so downstream feature code can be
  point-in-time correct (never peeks at the future).
- Scenarios are deliberately mixed. Some are loud (velocity bursts, 3 AM bookings),
  one is stealthy (mimics the victim's normal behaviour except for the mule
  destination and a new device) so behavioural models alone cannot catch everything
  and graph signals matter.
- Legitimate shippers also do "suspicious-looking" things at a low rate (new
  destination, new device, new payment instrument, off-hours booking) so that no
  single feature is a perfect separator.
- Popular legitimate hub addresses (fulfilment centres) exist so that raw fan-in
  on an address is NOT enough to flag a mule.
- Absolute metrics measured on this data describe the simulator, not production.
  Use it for relative comparison between approaches.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

START = pd.Timestamp("2026-01-05")

CITIES = ["Mumbai", "Delhi", "Bengaluru", "Chennai", "Hyderabad", "Kolkata", "Pune",
          "Ahmedabad", "Jaipur", "Lucknow", "Surat", "Nagpur", "Indore", "Bhopal",
          "Coimbatore", "Kochi", "Chandigarh", "Guwahati"]
SERVICES = ["ground", "express", "priority"]
CONTENTS = ["documents", "apparel", "electronics", "machinery_parts", "pharma",
            "food", "books", "cosmetics"]
RESELLABLE = ["electronics", "cosmetics", "pharma", "apparel"]
VALUE_PER_KG = {"documents": 200, "apparel": 900, "electronics": 6000,
                "machinery_parts": 1500, "pharma": 3500, "food": 300, "books": 400,
                "cosmetics": 2500}
SVC_BASE = {"ground": 60.0, "express": 140.0, "priority": 260.0}
SVC_PER_KG = {"ground": 25.0, "express": 55.0, "priority": 90.0}

# cohort: share of population, bookings/day, log-weight mean range, #destinations,
# service mix, share of bookings in business hours, lifetime-value proxy (INR/yr)
COHORTS = {
    "individual": dict(share=0.30, rate=(0.03, 0.10), logw=(-0.2, 0.7), ndest=(1, 3),
                       svc=[0.75, 0.20, 0.05], biz=0.60, ltv=2_000),
    "sme":        dict(share=0.45, rate=(0.15, 0.60), logw=(1.0, 2.2), ndest=(2, 6),
                       svc=[0.60, 0.30, 0.10], biz=0.90, ltv=60_000),
    "ecommerce":  dict(share=0.25, rate=(0.80, 2.00), logw=(0.2, 1.3), ndest=(6, 12),
                       svc=[0.50, 0.40, 0.10], biz=0.85, ltv=300_000),
}
HUB_ADDRESSES = [(f"hub_fc_{i}", c) for i, c in
                 enumerate(["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Kolkata"])]

# Fraud scenario knobs:
#  k: bookings per episode, span_days: episode duration, wmult: weight multiplier vs
#  victim's typical weight, svc: service mix (None = victim's own), offhours: P(00-05h),
#  origin_other: P(origin != victim's home), pay_ring: P(ring payment instrument),
#  dev_ring: P(ring device), resell: P(resellable contents)
SCENARIOS = {
    "velocity_burst":       dict(k=(5, 10), span_days=3 / 24, wmult=(1.0, 3.0), svc=[0.1, 0.6, 0.3],
                                 offhours=0.3, origin_other=0.2, pay_ring=0.5, dev_ring=0.8, resell=0.8),
    "geo_drift_heavy":      dict(k=(1, 3), span_days=2.0, wmult=(4.0, 10.0), svc=[0.1, 0.5, 0.4],
                                 offhours=0.3, origin_other=0.7, pay_ring=0.4, dev_ring=0.7, resell=0.9),
    "payment_swap":         dict(k=(2, 4), span_days=1.0, wmult=(1.5, 4.0), svc=[0.2, 0.6, 0.2],
                                 offhours=0.3, origin_other=0.2, pay_ring=1.0, dev_ring=0.6, resell=0.8),
    "off_hours_new_device": dict(k=(1, 3), span_days=1.0, wmult=(1.0, 3.0), svc=[0.3, 0.5, 0.2],
                                 offhours=1.0, origin_other=0.3, pay_ring=0.3, dev_ring=1.0, resell=0.7),
    "dormant_reactivation": dict(k=(2, 5), span_days=2.0, wmult=(2.0, 6.0), svc=[0.1, 0.6, 0.3],
                                 offhours=0.4, origin_other=0.5, pay_ring=0.6, dev_ring=0.9, resell=0.9),
    "stealthy_mule":        dict(k=(1, 3), span_days=5.0, wmult=(0.8, 1.5), svc=None,
                                 offhours=0.0, origin_other=0.0, pay_ring=0.0, dev_ring=0.7, resell=0.3),
}


@dataclass
class Shipper:
    sid: str
    idx: int
    cohort: str
    home: str
    rate: float
    logw_mu: float
    logw_sigma: float
    dests: list          # [(address_id, city)]
    dest_w: np.ndarray
    svc_p: np.ndarray
    biz: float
    contents_p: np.ndarray
    payment: str
    device: str
    account_created_days_before: float
    ltv: float


def shipping_charge(weight: float, service: str) -> float:
    return SVC_BASE[service] + SVC_PER_KG[service] * weight


def make_shippers(n: int, rng: np.random.Generator) -> list[Shipper]:
    names = list(COHORTS)
    shares = np.array([COHORTS[c]["share"] for c in names])
    out = []
    for i in range(n):
        c = str(rng.choice(names, p=shares))
        spec = COHORTS[c]
        nd = int(rng.integers(spec["ndest"][0], spec["ndest"][1] + 1))
        cities = rng.choice(CITIES, size=nd, replace=False)
        dests = [(f"addr_{i}_{k}", str(ci)) for k, ci in enumerate(cities)]
        if c == "ecommerce" or (c == "sme" and rng.random() < 0.3):
            hubs = rng.choice(len(HUB_ADDRESSES), size=int(rng.integers(1, 3)), replace=False)
            dests += [HUB_ADDRESSES[h] for h in hubs]
        out.append(Shipper(
            sid=f"S{i:04d}", idx=i, cohort=c, home=str(rng.choice(CITIES)),
            rate=float(rng.uniform(*spec["rate"])),
            logw_mu=float(rng.uniform(*spec["logw"])), logw_sigma=float(rng.uniform(0.35, 0.6)),
            dests=dests, dest_w=rng.dirichlet(np.ones(len(dests)) * 1.5),
            svc_p=np.array(spec["svc"]), biz=spec["biz"],
            contents_p=rng.dirichlet(np.ones(len(CONTENTS)) * 0.5),
            payment=f"pay_{i}", device=f"dev_{i}",
            account_created_days_before=float(rng.uniform(30, 1500)), ltv=spec["ltv"]))
    return out


def _row(sh, t_days, hour, addr, weight, service, contents, origin, payment, pay_age,
         device, is_fraud, scenario, ring_id, episode_id):
    ts = START + pd.Timedelta(days=int(t_days)) + pd.Timedelta(hours=float(hour))
    value = weight * VALUE_PER_KG[contents]
    return dict(ts=ts, shipper_id=sh.sid, cohort=sh.cohort, ltv=sh.ltv,
                account_age_days=round(sh.account_created_days_before + t_days, 1),
                origin_city=origin, dest_city=addr[1], dest_address_id=addr[0],
                weight_kg=round(weight, 2), service=service, contents=contents,
                declared_value=round(value, 0),
                charge_inr=round(shipping_charge(weight, service), 1),
                payment_id=payment, pay_age_min=round(pay_age, 1), device_id=device,
                is_fraud=is_fraud, scenario=scenario, ring_id=ring_id, episode_id=episode_id)


def legit_bookings(sh: Shipper, horizon: float, rng: np.random.Generator) -> list[dict]:
    rows, extra_pays, extra_devs = [], [], []
    n_new_addr = n_new_pay = n_new_dev = 0
    # Event times: Poisson process at the shipper's base rate, plus occasional legitimate
    # "sale day" bursts (6x rate within one business day) for business cohorts. These
    # bursts are what make velocity alone an unreliable fraud signal.
    times = []
    t = rng.exponential(1 / sh.rate)
    while t < horizon:
        times.append(t)
        t += rng.exponential(1 / sh.rate)
    if sh.cohort != "individual":
        for day in range(int(horizon)):
            if rng.random() < 0.02:
                k = rng.poisson(sh.rate * 6)
                times += list(day + rng.uniform(9 / 24, 18 / 24, k))
    for t in sorted(times):
        hour = rng.uniform(9, 18) if rng.random() < sh.biz else rng.uniform(0, 24)
        if rng.random() < 0.03:                      # genuinely new destination
            n_new_addr += 1
            addr = (f"addr_{sh.idx}_new{n_new_addr}", str(rng.choice(CITIES)))
            sh.dests.append(addr)
            sh.dest_w = np.append(sh.dest_w * 0.95, 0.05)
        else:
            addr = sh.dests[int(rng.choice(len(sh.dests), p=sh.dest_w))]
        weight = float(np.exp(rng.normal(sh.logw_mu, sh.logw_sigma)))
        service = SERVICES[int(rng.choice(3, p=sh.svc_p))]
        contents = CONTENTS[int(rng.choice(len(CONTENTS), p=sh.contents_p))]
        weight_v = weight * float(np.exp(rng.normal(0, 0.5)))
        origin = sh.home if rng.random() < 0.95 else str(rng.choice(CITIES))
        if rng.random() < 0.02:                      # legit new payment instrument
            n_new_pay += 1
            payment = f"pay_{sh.idx}_n{n_new_pay}"
            pay_age = rng.uniform(5, 3 * 24 * 60)
            extra_pays.append(payment)
        else:
            payment = sh.payment if (not extra_pays or rng.random() < 0.8) else extra_pays[-1]
            pay_age = (sh.account_created_days_before + t) * 1440
        if rng.random() < 0.04:                      # legit new device
            n_new_dev += 1
            device = f"dev_{sh.idx}_n{n_new_dev}"
            extra_devs.append(device)
        else:
            device = sh.device if (not extra_devs or rng.random() < 0.8) else extra_devs[-1]
        r = _row(sh, t, hour, addr, weight, service, contents, origin, payment, pay_age,
                 device, 0, "legit", "", "")
        r["declared_value"] = round(weight_v * VALUE_PER_KG[contents], 0)
        rows.append(r)
    return rows


def make_rings(n_rings: int, rng: np.random.Generator) -> list[dict]:
    rings = []
    for r in range(n_rings):
        rings.append(dict(
            rid=f"R{r}",
            addrs=[(f"mule_{r}_{k}", str(rng.choice(CITIES))) for k in range(int(rng.integers(2, 4)))],
            pays=[f"pay_ring{r}_{k}" for k in range(int(rng.integers(1, 3)))],
            devs=[f"dev_ring{r}_{k}" for k in range(int(rng.integers(2, 4)))]))
    return rings


def rotate_ring(ring: dict, rng: np.random.Generator):
    """Rings burn and replace infrastructure: before an episode, sometimes bring in a fresh
    mule address / device / payment instrument that no earlier fraud used. This is what
    keeps 'known-bad entity' lookups from being sufficient."""
    r = ring["rid"][1:]
    ring.setdefault("counters", {"addrs": len(ring["addrs"]), "devs": len(ring["devs"]), "pays": len(ring["pays"])})
    c = ring["counters"]
    if rng.random() < 0.5:
        ring["addrs"].append((f"mule_{r}_{c['addrs']}", str(rng.choice(CITIES)))); c["addrs"] += 1
    if rng.random() < 0.4:
        ring["devs"].append(f"dev_ring{r}_{c['devs']}"); c["devs"] += 1
    if rng.random() < 0.5:
        ring["pays"].append(f"pay_ring{r}_{c['pays']}"); c["pays"] += 1
    for key in ("addrs", "devs", "pays"):          # old infrastructure gets burned
        ring[key] = ring[key][-4:]


def fraud_episode(sh: Shipper, ring: dict, scenario: str, t0: float, rng: np.random.Generator,
                  ep_id: str) -> list[dict]:
    sc = SCENARIOS[scenario]
    k = int(rng.integers(sc["k"][0], sc["k"][1] + 1))
    times = t0 + np.sort(rng.uniform(0, sc["span_days"], k))
    rows = []
    for t in times:
        if rng.random() < sc["offhours"]:
            hour = rng.uniform(0, 5)
        else:
            hour = rng.uniform(9, 18) if rng.random() < sh.biz else rng.uniform(0, 24)
        addr = ring["addrs"][int(rng.integers(len(ring["addrs"])))]
        weight = float(np.exp(sh.logw_mu) * rng.uniform(*sc["wmult"]))
        svc_p = sh.svc_p if sc["svc"] is None else np.array(sc["svc"])
        service = SERVICES[int(rng.choice(3, p=svc_p))]
        if rng.random() < sc["resell"]:
            contents = str(rng.choice(RESELLABLE))
        else:
            contents = CONTENTS[int(rng.choice(len(CONTENTS), p=sh.contents_p))]
        origin = str(rng.choice(CITIES)) if rng.random() < sc["origin_other"] else sh.home
        if rng.random() < sc["pay_ring"]:
            payment, pay_age = ring["pays"][int(rng.integers(len(ring["pays"])))], rng.uniform(2, 45)
        else:
            payment, pay_age = sh.payment, (sh.account_created_days_before + t) * 1440
        device = ring["devs"][int(rng.integers(len(ring["devs"])))] if rng.random() < sc["dev_ring"] else sh.device
        r = _row(sh, t, hour, addr, weight, service, contents, origin, payment, pay_age, device,
                 1, scenario, ring["rid"], ep_id)
        r["declared_value"] = round(r["declared_value"] * float(np.exp(rng.normal(0.3, 0.4))), 0)
        rows.append(r)
    return rows


def generate(n_shippers: int = 300, horizon_days: float = 120, n_rings: int = 6,
             n_episodes: int = 70, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    shippers = make_shippers(n_shippers, rng)
    rings = make_rings(n_rings, rng)
    legit = {sh.sid: legit_bookings(sh, horizon_days, rng) for sh in shippers}

    victims = rng.choice(len(shippers), size=n_episodes, replace=False)
    scen_names = list(SCENARIOS)
    # plan episodes first, then run them in time order so ring rotation is causal
    plan = []
    for e, vi in enumerate(victims):
        scenario = scen_names[e % len(scen_names)]        # balanced scenario mix
        if scenario == "dormant_reactivation":
            t0 = float(rng.uniform(75, horizon_days - 3))
        else:
            t0 = float(rng.uniform(25, horizon_days - 6))
        plan.append((t0, e, int(vi), scenario, int(rng.integers(n_rings))))
    fraud_rows = []
    for t0, e, vi, scenario, ri in sorted(plan):
        sh, ring = shippers[vi], rings[ri]
        if scenario == "dormant_reactivation":
            # the account went quiet for ~90 days before the takeover
            legit[sh.sid] = [r for r in legit[sh.sid]
                             if not (t0 - 90 <= (r["ts"] - START).total_seconds() / 86400 < t0)]
        rotate_ring(ring, rng)
        fraud_rows += fraud_episode(sh, ring, scenario, t0, rng, f"E{e:03d}")

    rows = [r for rs in legit.values() for r in rs] + fraud_rows
    df = pd.DataFrame(rows).sort_values("ts", kind="stable").reset_index(drop=True)
    df.insert(0, "booking_id", [f"B{i:06d}" for i in range(len(df))])
    df["hour"] = df["ts"].dt.hour + df["ts"].dt.minute / 60.0
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bookings.csv")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--shippers", type=int, default=300)
    ap.add_argument("--days", type=float, default=120)
    ap.add_argument("--episodes", type=int, default=70)
    a = ap.parse_args()
    d = generate(a.shippers, a.days, n_episodes=a.episodes, seed=a.seed)
    d.to_csv(a.out, index=False)
    print(f"{len(d)} bookings, {d.is_fraud.sum()} fraud ({d.is_fraud.mean():.2%}), "
          f"{d.shipper_id.nunique()} shippers, {d.ts.min().date()} → {d.ts.max().date()}")
    print(d[d.is_fraud == 1].scenario.value_counts().to_string())
