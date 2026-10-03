"""E5 — harness sanity check: train E2 on labels shuffled *within* TRANSFER.

Shuffling keeps the payment-type rule intact (fraud stays TRANSFER-only) but destroys any link
between fraud and the other features. The test is scored on the true labels.
* If the harness is sound, TRANSFER-scope ROC-AUC lands near 0.5.
* If E2's real-label TRANSFER AUC is not clearly above this null distribution, E2 found no signal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _dataco_common import F, P, save_scores  # noqa: E402

N_PERM = 20


def main():
    o = F.cached_orders()
    cols = F.honest_features(include_payment=True)
    F.assert_no_leak(cols)
    tr, va, te = F.split(o)
    Xtr, Xva, Xte = F.matrix(tr, cols), F.matrix(va, cols), F.matrix(te, cols)

    def shuffled(d, rng):
        y = d.is_fraud.values.copy()
        m = (d.payment_type == "TRANSFER").values
        y[m] = rng.permutation(y[m])
        return y

    real = P.train_gbm(Xtr, tr.is_fraud.values, Xva, va.is_fraud.values, seed=1).predict_proba(Xte)[:, 1]
    real_auc = P.evaluate(te, real)["transfer"]["roc_auc"]
    null = []
    for k in range(N_PERM):
        rng = np.random.default_rng(100 + k)
        m = P.train_gbm(Xtr, shuffled(tr, rng), Xva, shuffled(va, rng), seed=1)
        null.append(P.evaluate(te, m.predict_proba(Xte)[:, 1])["transfer"]["roc_auc"])
    null = np.array(null)
    p_emp = (1 + (null >= real_auc).sum()) / (1 + len(null))

    P.write(HERE / "results.md", f"""
# E5 — label-shuffle null (within TRANSFER)

Same features and model as E2 (with payment_type, single seed). {N_PERM} permutations of the training and
validation labels inside TRANSFER; test scored on true labels.

| | TRANSFER-scope test ROC-AUC |
|---|---:|
| real labels (seed 1) | {real_auc:.3f} |
| shuffled labels: mean ± sd | {null.mean():.3f} ± {null.std():.3f} |
| shuffled labels: min – max | {null.min():.3f} – {null.max():.3f} |
| empirical p-value (real ≤ null) | {p_emp:.3f} |

A p-value well above 0.05 means the real-label model is indistinguishable from one trained on noise
inside TRANSFER.
""")
    save_scores(HERE, dict(real_auc=real_auc, null=null.tolist(), p_value=p_emp))


if __name__ == "__main__":
    main()
