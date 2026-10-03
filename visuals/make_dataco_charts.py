"""Charts for the DataCo real-data study. Run after experiments e0–e5 and demo_dataco.py.

Writes
  visuals/dataco_transfer_auc.png    TRANSFER-scope ROC-AUC (95% CI) per model, with the shuffle-null band
  visuals/dataco_fraud_by_month.png  monthly fraud rate: all orders vs TRANSFER orders
  visuals/dataco_policy_cost.png     realised cost per decision policy on the replay window
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "visuals"
sys.path.insert(0, str(ROOT / "prototypes" / "data"))
import dataco_features as F  # noqa: E402

# reference palette (light mode): categorical slots 1–2, neutral ink for text, recessive grid
BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.axisbelow": True, "text.color": INK, "font.size": 10,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
})


def _load(exp: str) -> dict:
    return json.loads((ROOT / "experiments" / exp / "scores.json").read_text(encoding="utf-8"))


def transfer_auc():
    rows = []
    for exp, keys in [("e0-dataco-leaky-baseline", ["leaky: honest + post-booking columns"]),
                      ("e2-dataco-honest-gbm", ["honest GBM (with payment_type)", "honest GBM (no payment_type)"]),
                      ("e3-dataco-entity-graph", ["GBM + entity counters (with payment_type)"]),
                      ("e4-dataco-anomaly", ["IsolationForest × TRANSFER gate", "customer drift × TRANSFER gate"])]:
        m = _load(exp)["metrics"]
        for k in keys:
            t = m[k]["transfer"]
            rows.append((k, t["roc_auc"], t["roc_ci"], exp.startswith("e0")))
    null = np.array(_load("e5-dataco-label-shuffle")["null"])

    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.axvspan(null.min(), null.max(), color=GRID, alpha=0.9, lw=0, label="shuffled-label null (E5, min–max)")
    ax.axvline(0.5, color=INK2, lw=1, ls=(0, (3, 3)))
    for i, (k, v, ci, leaky) in enumerate(rows[::-1]):
        c = ORANGE if leaky else BLUE
        ax.plot(ci, [i, i], color=c, lw=2, solid_capstyle="round")
        ax.plot([v], [i], "o", ms=8, color=c, mec=SURFACE, mew=2)
        ax.text(ci[1] + 0.008, i, f"{v:.3f}", va="center", color=INK, fontsize=9)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows[::-1]])
    ax.set_xlim(0.44, 1.02)
    ax.set_xlabel("ROC-AUC inside TRANSFER orders, test window (95% bootstrap CI)")
    fig.suptitle("Only the leaky model separates fraud from other TRANSFER orders", x=0.01, ha="left", fontsize=11)
    ax.plot([], [], "o", color=BLUE, label="booking-time features (honest)")
    ax.plot([], [], "o", color=ORANGE, label="post-booking columns (leak)")
    ax.legend(loc="lower right", frameon=False, fontsize=8.5)
    ax.grid(axis="y", visible=False)
    fig.tight_layout(); fig.savefig(OUT / "dataco_transfer_auc.png", dpi=160); plt.close(fig)


def fraud_by_month():
    o = F.cached_orders()
    m = o.groupby(o.ts.dt.to_period("M"))
    all_rate = m.is_fraud.mean()
    tr = o[o.payment_type == "TRANSFER"]
    tr_rate = tr.groupby(tr.ts.dt.to_period("M")).is_fraud.mean()
    x = all_rate.index.to_timestamp()
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.plot(x, tr_rate.values * 100, color=ORANGE, lw=2)
    ax.plot(x, all_rate.values * 100, color=BLUE, lw=2)
    for name, (a, _) in F.SPLITS.items():
        ax.axvline(np.datetime64(a), color=INK2, lw=0.8, ls=(0, (2, 3)))
        ax.text(np.datetime64(a), 13.6, f" {name}", color=INK2, fontsize=8, va="top")
    ax.set_ylim(0, 14); ax.set_ylabel("fraud orders, % of orders")
    ax.plot([], [], color=ORANGE, lw=2, label="TRANSFER orders"); ax.plot([], [], color=BLUE, lw=2, label="all orders")
    ax.legend(loc="center left", frameon=False, fontsize=8.5, ncol=2, bbox_to_anchor=(0, 0.36))
    fig.suptitle("Fraud rate is flat over time, and all of it sits in TRANSFER", x=0.01, ha="left", fontsize=11)
    fig.tight_layout(); fig.savefig(OUT / "dataco_fraud_by_month.png", dpi=160); plt.close(fig)


def policy_cost():
    s = json.loads((ROOT / "prototypes" / "fraudshield-pipeline" / "stats_dataco.json").read_text(encoding="utf-8"))
    pols = list(s["policies"])
    cost = [s["policies"][p]["cost_usd"] / 1000 for p in pols]
    stopped = [s["policies"][p]["fraud_stopped"] for p in pols]
    fig, ax = plt.subplots(figsize=(8, 3.4))
    y = np.arange(len(pols))[::-1]
    ax.barh(y, cost, height=0.55, color=BLUE)
    for yi, c, st in zip(y, cost, stopped):
        ax.text(c + 3, yi, f"{c:,.0f}k USD · {st}/{s['n_fraud']} fraud stopped", va="center", fontsize=9, color=INK)
    ax.set_yticks(y, pols); ax.set_xlim(0, max(cost) * 1.75)
    ax.set_xlabel("realised cost, thousand USD (simulated step-up/review outcomes)")
    fig.suptitle("The cost-sensitive policy wins by choosing actions well, not by ranking better", x=0.01, ha="left", fontsize=11)
    ax.grid(axis="y", visible=False)
    fig.tight_layout(); fig.savefig(OUT / "dataco_policy_cost.png", dpi=160); plt.close(fig)


if __name__ == "__main__":
    transfer_auc(); fraud_by_month(); policy_cost()
    print("wrote", *(p.name for p in sorted(OUT.glob("dataco_*.png"))))
