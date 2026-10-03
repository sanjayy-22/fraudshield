"""E4 — unsupervised: is fraud *unusual* in any way the features can see?

No labels used for scoring. Two detectors, fitted on train-split TRANSFER orders:
* IsolationForest on the numeric booking-time + history features;
* per-customer drift: how far this order's spend / content / timing departs from the customer's
  own history (the experiments/c-behavioral-drift idea; first orders get the population baseline).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _dataco_common import F, P, save_scores  # noqa: E402

NUM = F.BASE_NUM_COLS + F.HISTORY_COLS


def drift_score(d):
    has_hist = d.cust_n_prior > 0
    spend = np.where(has_hist, np.abs(np.log(d.cust_spend_ratio.clip(lower=1e-3))), 0.0)
    burst = d.cust_orders_7d + 0.3 * d.cust_orders_30d
    novelty = d.cust_new_country * has_hist
    return spend + burst + novelty


def main():
    o = F.cached_orders()
    tr, _, te = F.split(o)
    F.assert_no_leak(NUM)
    fit = tr[tr.payment_type == "TRANSFER"]
    iso = IsolationForest(n_estimators=300, random_state=1).fit(fit[NUM].values)
    s_iso = -iso.score_samples(te[NUM].values)           # higher = more anomalous
    s_drift = drift_score(te).values
    # within the all-orders scope, gate both by the TRANSFER rule so the comparison with E1/E2 is fair
    gate = te.is_transfer.values
    rows = {"IsolationForest × TRANSFER gate": P.evaluate(te, s_iso * 1e-3 + gate),
            "customer drift × TRANSFER gate": P.evaluate(te, s_drift * 1e-3 + gate)}
    P.write(HERE / "results.md", f"""
# E4 — unsupervised anomaly

Scores are added to the TRANSFER indicator (scaled so the rule dominates), so in the all-orders
scope they only re-rank within each payment group; the TRANSFER-scope row is the pure anomaly ranking.

## Test metrics
{P.metrics_table(rows)}

An ROC-AUC near 0.5 in the TRANSFER scope means fraudulent orders are no more anomalous than legitimate ones
on these features.
""")
    save_scores(HERE, dict(metrics=rows, scores={"iso": s_iso.round(6).tolist(), "drift": s_drift.round(6).tolist()},
                           y=te.is_fraud.tolist(), transfer=(te.payment_type == "TRANSFER").tolist()))


if __name__ == "__main__":
    main()
