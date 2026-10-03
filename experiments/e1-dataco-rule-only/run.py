"""E1 — the one-line rule: flag every TRANSFER order.

Every SUSPECTED_FRAUD order in DataCo is a TRANSFER order, so `payment_type == TRANSFER` is the floor
every model has to beat. Inside the TRANSFER scope the rule is constant, so its AUC there is 0.5 by
construction — the transfer scope is where a model has to earn its keep.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _dataco_common import F, P, save_scores  # noqa: E402


def main():
    o = F.cached_orders()
    _, _, te = F.split(o)
    s = te.is_transfer.values.astype(float)
    rows = {"rule: payment_type == TRANSFER": P.evaluate(te, s)}

    by_pay = o.groupby("payment_type").agg(orders=("is_fraud", "size"), fraud=("is_fraud", "sum"))
    by_pay["fraud_rate"] = by_pay.fraud / by_pay.orders
    pay_md = "\n".join(["| payment_type | orders | fraud orders | fraud rate |", "|---|---:|---:|---:|"] +
                       [f"| {k} | {int(r.orders)} | {int(r.fraud)} | {r.fraud_rate:.4f} |" for k, r in by_pay.iterrows()])
    ct = o.groupby(["payment_type", "order_status"]).size().unstack(fill_value=0)
    ct_md = "\n".join(["| order_status | " + " | ".join(ct.index) + " |", "|---|" + "---:|" * len(ct.index)] +
                      [f"| {st} | " + " | ".join(str(ct.loc[p, st]) for p in ct.index) + " |" for st in ct.columns])

    y, t = te.is_fraud.values, te.is_transfer.values
    flagged, caught = int(t.sum()), int((y & t).sum())
    P.write(HERE / "results.md", f"""
# E1 — rule only: flag TRANSFER

## Fraud by payment type (all orders, 2015-01 → 2018-01)
{pay_md}

## payment_type × order_status (orders)
Each status occurs under exactly one payment type, so `payment_type` looks like it was generated from
the status. It may well be known at booking time in a real system, but treat any signal in it with suspicion.

{ct_md}

## Test metrics
{P.metrics_table(rows)}

On the test window the rule flags {flagged} of {len(te)} orders ({flagged/len(te):.1%}) and catches
{caught} of {int(y.sum())} frauds ({caught/max(int(y.sum()),1):.0%}). Precision is {caught/flagged:.3f}.
""")
    save_scores(HERE, dict(metrics=rows, scores=s.tolist(), y=y.tolist(), transfer=t.astype(bool).tolist()))


if __name__ == "__main__":
    main()
