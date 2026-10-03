"""E0 — the leaky baseline: what you get if post-booking columns are left in.

Many published DataCo "fraud detection" notebooks report ~99 % accuracy/AUC. This experiment
reproduces that number and shows where it comes from: the model leans on `delivery_status`
('Shipping canceled'), which is recorded *after* the order was stopped. Not a deployable model.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _dataco_common import F, P, save_scores  # noqa: E402


def main():
    o = F.cached_orders()
    tr, va, te = F.split(o)
    variants = {
        "leaky: honest + post-booking columns": F.honest_features() + F.LEAKY_ORDER_COLS,
        "leaky: post-booking columns only": F.LEAKY_ORDER_COLS,
    }
    rows, imps, scores = {}, {}, {}
    for label, cols in variants.items():
        m = P.train_gbm(F.matrix(tr, cols), tr.is_fraud.values, F.matrix(va, cols), va.is_fraud.values)
        s = m.predict_proba(F.matrix(te, cols))[:, 1]
        rows[label] = P.evaluate(te, s)
        imps[label] = P.importance(m, cols, F.matrix(te, cols))
        scores[label] = s.round(6).tolist()

    o_ = o.copy()
    audit = o_.groupby("delivery_status").agg(orders=("is_fraud", "size"), fraud=("is_fraud", "sum"))
    audit["fraud_rate"] = audit.fraud / audit.orders
    audit_md = "\n".join(["| delivery_status | orders | fraud orders | fraud rate |", "|---|---:|---:|---:|"] +
                         [f"| {k} | {int(r.orders)} | {int(r.fraud)} | {r.fraud_rate:.3f} |" for k, r in audit.iterrows()])

    first = next(iter(imps))
    P.write(HERE / "results.md", f"""
# E0 — leaky baseline (NOT deployable)

Post-booking columns added on top of the honest feature set: `leak_canceled` (delivery_status =
'Shipping canceled'), `leak_late_risk` (late_delivery_risk), `leak_days_real` (days_shipping_real),
`leak_delay_minus_sched`. `order_status` itself is excluded (it *is* the label).

## Split
{P.split_summary(o)}

## Test metrics
{P.metrics_table(rows)}

## Why it looks so good: `delivery_status` by fraud (all orders)
{audit_md}

Every fraud order is 'Shipping canceled'. The only other orders with that status are the
CANCELED ones, so this one post-event column narrows fraud to roughly a 50/50 group.

## Top features — {first}
{P.importance_table(imps[first])}

**Conclusion.** The ~0.99 AUC is the leak, not detection. In a booking-time system none of these columns exist yet.
""")
    save_scores(HERE, dict(metrics=rows, scores=scores, y=te.is_fraud.tolist(),
                           transfer=(te.payment_type == "TRANSFER").tolist()))


if __name__ == "__main__":
    main()
