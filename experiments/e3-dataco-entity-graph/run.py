"""E3 — entity-graph counters: does fraud cluster on shared entities?

Each order links a customer, a destination city and a product. If fraud were organised (rings,
mule destinations, targeted products), recent fraud on the same city / product / customer home
city would raise the risk of the next order — the signal experiments/b-entity-graph found in the
synthetic stream. Two views:
1. homophily: fraud rate of TRANSFER orders whose linked entity had recent (label-delayed) fraud vs not;
2. the E2 GBM plus the entity counters.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _dataco_common import F, P, save_scores  # noqa: E402
sys.path.insert(0, str(HERE.parent / "e2-dataco-honest-gbm"))
from run import run_variant  # noqa: E402


def homophily(o: pd.DataFrame) -> str:
    t = o[(o.payment_type == "TRANSFER") & (o.split != "none")]
    lines = ["| linked entity signal (TRANSFER orders) | orders with signal | fraud rate with | fraud rate without | ratio |",
             "|---|---:|---:|---:|---:|"]
    checks = {
        "destination city had fraud in last 30 d": t.city_fraud_30d > 0,
        "destination city fraud rate (90 d) in top decile": t.city_fraud_rate_90d >= t.city_fraud_rate_90d.quantile(0.9),
        "main product had ≥ median fraud in last 30 d": t.product_fraud_30d >= t.product_fraud_30d.median(),
        "customer home city fraud (90 d) in top decile": t.custcity_fraud_90d >= t.custcity_fraud_90d.quantile(0.9),
        "customer had a prior fraud order": t.cust_prior_fraud > 0,
        "customer had a prior canceled order": t.cust_prior_cancel > 0,
    }
    for name, mask in checks.items():
        a, b = t[mask].is_fraud.mean(), t[~mask].is_fraud.mean()
        lines.append(f"| {name} | {int(mask.sum())} | {a:.4f} | {b:.4f} | {a / b:.2f} |")
    return "\n".join(lines)


def main():
    o = F.cached_orders()
    _, _, te = F.split(o)
    variants = {"GBM + entity counters (with payment_type)": F.honest_features(True, True),
                "GBM + entity counters (no payment_type)": F.honest_features(False, True)}
    rows, scores, notes = {}, {}, []
    for label, cols in variants.items():
        s, m, per_seed, _ = run_variant(o, cols)
        rows[label] = P.evaluate(te, s)
        scores[label] = s.round(6).tolist()
        notes.append(f"- {label}: TRANSFER-scope ROC-AUC per seed {', '.join(f'{v:.3f}' for v in per_seed)}")

    P.write(HERE / "results.md", f"""
# E3 — entity-graph counters

Counters (all label-delayed by 1 day, strictly earlier orders): `city_orders_7d`, `city_fraud_30d`,
`city_fraud_rate_90d`, `product_fraud_30d`, `product_fraud_rate_90d`, `custcity_fraud_90d`.

## Homophily check (train + valid + test, TRANSFER only)
If fraud were organised around shared entities, the "with" rate would clearly exceed the "without" rate.

{homophily(o)}

## Test metrics
{P.metrics_table(rows)}

{chr(10).join(notes)}
""")
    save_scores(HERE, dict(metrics=rows, scores=scores, y=te.is_fraud.tolist(),
                           transfer=(te.payment_type == "TRANSFER").tolist()))


if __name__ == "__main__":
    main()
