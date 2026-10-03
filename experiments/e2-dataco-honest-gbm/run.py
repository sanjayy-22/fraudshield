"""E2 — the honest model: LightGBM on booking-time features only.

Features: order content, shipping choice, geography, time of day, and point-in-time customer
history (strictly earlier orders; fraud/cancel outcomes visible after a 1-day delay). Run twice:
with `payment_type` (is_transfer) and without it, because payment_type partitions order_status.
The question is the TRANSFER-scope row: does the model rank fraud above legitimate TRANSFER orders?
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _dataco_common import F, P, save_scores  # noqa: E402

SEEDS = [1, 2, 3, 4, 5]


def run_variant(o, cols, seeds=SEEDS):
    F.assert_no_leak(cols)
    tr, va, te = F.split(o)
    Xtr, Xva, Xte = F.matrix(tr, cols), F.matrix(va, cols), F.matrix(te, cols)
    preds, models = [], []
    for sd in seeds:
        m = P.train_gbm(Xtr, tr.is_fraud.values, Xva, va.is_fraud.values, seed=sd)
        preds.append(m.predict_proba(Xte)[:, 1]); models.append(m)
    s = np.mean(preds, axis=0)                     # seed-averaged score
    per_seed = [P.evaluate(te, p)["transfer"]["roc_auc"] for p in preds]
    return s, models[0], per_seed, Xte


def main():
    o = F.cached_orders()
    _, _, te = F.split(o)
    variants = {"honest GBM (with payment_type)": F.honest_features(include_payment=True),
                "honest GBM (no payment_type)": F.honest_features(include_payment=False)}
    rows, scores, notes, imp_md = {}, {}, [], {}
    for label, cols in variants.items():
        s, m, per_seed, Xte = run_variant(o, cols)
        rows[label] = P.evaluate(te, s)
        scores[label] = s.round(6).tolist()
        notes.append(f"- {label}: best iterations {m.best_iteration_} (seed 1); TRANSFER-scope ROC-AUC per seed "
                     f"{', '.join(f'{v:.3f}' for v in per_seed)}")
        imp_md[label] = P.importance_table(P.importance(m, cols, Xte))

    t = rows["honest GBM (with payment_type)"]["transfer"]
    if t["roc_ci"][0] <= 0.5:
        verdict = "includes 0.5, so no ranking signal inside TRANSFER is detectable on this test window"
    elif t["roc_auc"] < 0.6:
        verdict = (f"only just excludes 0.5. The signal is weak but detectable. PR lift is {t['pr_lift']:.2f}×, "
                   "which is operationally negligible (see E5 for the permutation test)")
    else:
        verdict = "excludes 0.5, so there is real ranking signal inside TRANSFER"
    P.write(HERE / "results.md", f"""
# E2 — honest booking-time GBM

Score = mean of {len(SEEDS)} LightGBM seeds, early-stopped on the 2017-H1 validation split (PR-AUC).
No leak / identifier column can enter: `assert_no_leak()` runs on every feature list.

## Test metrics
{P.metrics_table(rows)}

{chr(10).join(notes)}

## Reading
- The **all-orders** ROC-AUC with payment_type is essentially the E1 rule: the model learned "TRANSFER".
- The **TRANSFER-scope** ROC-AUC 95% interval is [{t['roc_ci'][0]:.3f}, {t['roc_ci'][1]:.3f}]. It {verdict}.
- Without payment_type, the all-orders ROC-AUC falls to about chance: payment type carries nearly all the signal.
- The bootstrap interval covers test-set sampling only; the per-seed spread above adds model variance on top.

## Feature importance — with payment_type (seed 1, SHAP on test)
{imp_md['honest GBM (with payment_type)']}

## Feature importance — no payment_type (seed 1, SHAP on test)
{imp_md['honest GBM (no payment_type)']}

Importances of a model with ~chance-level ranking describe noise it fitted, not fraud drivers.
""")
    save_scores(HERE, dict(metrics=rows, scores=scores, y=te.is_fraud.tolist(),
                           transfer=(te.payment_type == "TRANSFER").tolist()))


if __name__ == "__main__":
    main()
