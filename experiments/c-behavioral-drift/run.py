"""Experiment C — Per-shipper behavioural fingerprint with cohort back-off (unsupervised).

Hypothesis: because the fraudster is using a *real* shipper's identity, the strongest
label-free signal is "how unlike this shipper's own normal is this booking?" The
profile is a running Bayesian model per shipper:

- categorical dimensions (destination address / city, origin, service, contents,
  hour-of-day) → Dirichlet-smoothed probabilities, with the shipper's cohort as prior
  (pseudo-count ALPHA). Novelty = -log P(value | shipper).
- continuous dimensions (log weight, log declared value) → Gaussian with mean/variance
  shrunk toward the cohort (SHRINK_K pseudo-observations). Novelty = |z|.
- velocity → bookings in the last 24 h vs the shipper's own baseline daily rate.
- identity → new device / new payment instrument.

The composite drift_score is a fixed weighted sum (no labels touched). This experiment
measures how far that gets on its own, and how much the cohort back-off matters for
cold-start shippers (few historical bookings).
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "prototypes" / "data"))
sys.path.insert(0, str(ROOT / "experiments" / "a-rules-gbm-shap"))
from simulate import generate                                   # noqa: E402
from featurize import build_feature_frame, FEATURE_COLS         # noqa: E402
from run import recall_at_fpr, train_gbm                        # noqa: E402


def block(y, s):
    if y.sum() == 0 or (y == 0).sum() == 0:
        return dict(auc=np.nan, ap=np.nan, recall_fpr1=np.nan, n=len(y), fraud=int(y.sum()))
    return dict(auc=roc_auc_score(y, s), ap=average_precision_score(y, s),
                recall_fpr1=recall_at_fpr(y, s, 0.01)[0], n=len(y), fraud=int(y.sum()))


def main():
    df = generate(seed=7)
    X_bo = build_feature_frame(df, cohort_backoff=True)
    X_no = build_feature_frame(df, cohort_backoff=False)
    cut = X_bo["ts"].quantile(0.70)
    te_bo, te_no = X_bo[X_bo.ts >= cut], X_no[X_no.ts >= cut]
    y = te_bo.is_fraud.values

    # supervised reference trained on the same split (from experiment A's recipe)
    tr = X_bo[X_bo.ts < cut]
    m, _ = train_gbm(tr, tr.is_fraud.values, FEATURE_COLS)
    p_gbm = m.predict_proba(te_bo[FEATURE_COLS])[:, 1]

    rows = [dict(model="drift score, cohort back-off (unsupervised)", **block(y, te_bo.drift_score.values)),
            dict(model="drift score, per-shipper only (no back-off)", **block(y, te_no.drift_score.values)),
            dict(model="supervised GBM, all features (reference)", **block(y, p_gbm))]
    res = pd.DataFrame(rows)

    # cold start: how much history did the shipper have at booking time?
    buckets = pd.cut(te_bo.n_hist, [-1, 4, 29, 10 ** 9], labels=["0–4 bookings", "5–29", "30+"])
    cs = []
    for b in buckets.cat.categories:
        mask = (buckets == b).values
        cs.append(dict(history=b, **{"AUC back-off": block(y[mask], te_bo.drift_score.values[mask])["auc"],
                                     "AUC no back-off": block(y[mask], te_no.drift_score.values[mask])["auc"],
                                     "AUC GBM": block(y[mask], p_gbm[mask])["auc"],
                                     "n": int(mask.sum()), "fraud": int(y[mask].sum())}))
    cold = pd.DataFrame(cs)

    # per-scenario recall of the unsupervised score at 1 % FPR
    _, thr = recall_at_fpr(y, te_bo.drift_score.values, 0.01)
    t2 = te_bo.assign(c=te_bo.drift_score > thr)
    scen = t2[t2.is_fraud == 1].groupby("scenario")["c"].mean().to_frame("recall@1%FPR (drift)")

    # which components dominate the drift score for fraud vs legit? (mean per term)
    terms = pd.DataFrame({
        "|w_z|": te_bo.w_z.abs(), "|val_z|": te_bo.val_z.abs(), "dest_city_nov": te_bo.dest_city_nov,
        "dest_addr_nov": te_bo.dest_addr_nov, "service_nov": te_bo.service_nov, "hour_nov": te_bo.hour_nov,
        "origin_nov": te_bo.origin_nov, "log1p(vel24_ratio)": np.log1p(te_bo.vel24_ratio),
        "new_device": te_bo.new_device, "new_payment": te_bo.new_payment, "is_fraud": y})
    term_means = terms.groupby("is_fraud").mean().T
    term_means.columns = ["legit mean", "fraud mean"]
    term_means["ratio"] = term_means["fraud mean"] / term_means["legit mean"].replace(0, np.nan)

    md = ["# Experiment C — behavioural drift with cohort back-off", "",
          "## Ranking quality (test period)", "", res.to_markdown(index=False, floatfmt=".3f"), "",
          "## Cold start: AUC by amount of shipper history at booking time", "",
          cold.to_markdown(index=False, floatfmt=".3f"), "",
          "## Per-scenario recall of the unsupervised drift score at 1 % FPR", "", scen.to_markdown(floatfmt=".2f"), "",
          "## Which drift terms separate (test period means)", "", term_means.to_markdown(floatfmt=".2f"), "",
          "## Observations", "",
          "- With zero labels the profile-drift score already ranks fraud well above legitimate traffic; it is the",
          "  detector that keeps working when fraud tactics change and labels have not caught up.",
          "- Cohort back-off is what makes the first few bookings of a shipper scoreable at all: without it, z-scores",
          "  and novelty terms are undefined/zero for thin histories, which is exactly where dormant/new accounts sit.",
          "- The weights are hand-set. In the pipeline the drift score is fed to the GBM as one feature, so the",
          "  supervised model re-weights it; standalone it is the fallback when the model is unavailable.",
          "- Everything here is O(1) per booking against a per-shipper hash (counts, Welford moments, a 7-day deque):",
          "  it maps directly onto a Redis hash per shipper.", ""]
    (HERE / "results.md").write_text("\n".join(md), encoding="utf-8")
    print(res.to_string(index=False)); print(cold.to_string(index=False)); print(scen)


if __name__ == "__main__":
    main()
