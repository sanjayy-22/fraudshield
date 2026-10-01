"""Experiment A — Rules engine + gradient-boosted classifier + SHAP-style attributions.

Supervised tabular approach on point-in-time features. Time-based split (first 70 % of
the stream trains, last 30 % tests) so the evaluation mimics deployment: the model
never sees the future, and delayed labels are only visible after their delay.

Outputs (written next to this file):
  results.md      metrics, per-scenario recall, top features
  model.pkl       trained model + feature list (re-used by experiment D and the pipeline)
  example_evidence.json  contribution breakdown of one caught fraud booking
"""
from __future__ import annotations

import json
import pickle
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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "prototypes" / "data"))
from simulate import generate                                   # noqa: E402
from featurize import build_feature_frame, FEATURE_COLS, BEHAV_COLS  # noqa: E402


# ----------------------------------------------------------------- rules engine
RULES = [
    ("R01_NEW_PAY_NEW_DEST_EXPRESS", 0.60, "payment instrument added <60 min ago + never-seen destination + express/priority",
     lambda f: f["new_payment"] == 1 and f["log_pay_age_min"] < np.log1p(60) and f["dest_addr_seen"] == 0 and f["is_express"] == 1),
    ("R02_VELOCITY_SPIKE", 0.50, "≥5 bookings in the last hour and >8× the shipper's daily baseline",
     lambda f: f["vel_1h"] >= 5 and f["vel24_ratio"] > 8),
    ("R03_DORMANT_REACTIVATION", 0.50, "no bookings for ≥60 days, then a new destination from a new device",
     lambda f: f["days_since_last"] >= 60 and f["dest_addr_seen"] == 0 and f["new_device"] == 1),
    ("R04_KNOWN_MULE_DEST", 0.80, "destination address linked to ≥2 confirmed fraud shipments",
     lambda f: f["dest_fraud"] >= 2),
    ("R05_SHARED_FRAUD_DEVICE", 0.70, "device previously used on confirmed-fraud bookings, new to this shipper",
     lambda f: f["dev_fraud"] >= 1 and f["new_device"] == 1),
    ("R06_WEIGHT_OUTLIER", 0.30, "weight >4σ above the shipper's own history",
     lambda f: f["w_z"] > 4),
    ("R07_OFFHOURS_NEW_DEVICE_NEW_DEST", 0.40, "booked 00:00–05:00 from a new device to a new destination",
     lambda f: f["hour"] < 5 and f["new_device"] == 1 and f["dest_addr_seen"] == 0),
]


def rule_score(f: dict) -> tuple[float, list[str]]:
    hits = [(code, w) for code, w, _, pred in RULES if pred(f)]
    s = 1.0 - float(np.prod([1 - w for _, w in hits])) if hits else 0.0
    return s, [c for c, _ in hits]


# ----------------------------------------------------------------- metrics
def recall_at_fpr(y, s, fpr):
    neg = np.sort(s[y == 0])[::-1]
    thr = neg[int(fpr * len(neg))] if len(neg) else np.inf
    return float((s[y == 1] > thr).mean()), float(thr)


def summarize(y, s, name):
    from sklearn.metrics import roc_auc_score, average_precision_score
    r1, t1 = recall_at_fpr(y, s, 0.01)
    r05, _ = recall_at_fpr(y, s, 0.005)
    return dict(model=name, auc=roc_auc_score(y, s), ap=average_precision_score(y, s),
                recall_fpr1=r1, recall_fpr05=r05, thr_fpr1=t1)


def train_gbm(X, y, cols):
    try:
        import lightgbm as lgb
        m = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.04, num_leaves=31, min_child_samples=25,
                               subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                               reg_lambda=2.0, scale_pos_weight=5.0, verbose=-1, random_state=1)
        m.fit(X[cols], y)
        return m, "lightgbm"
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingClassifier
        m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, class_weight="balanced", random_state=1)
        m.fit(X[cols], y)
        return m, "sklearn-hgb"


def main():
    df = generate(seed=7)
    X = build_feature_frame(df)
    cut = X["ts"].quantile(0.70)
    tr, te = X[X.ts < cut], X[X.ts >= cut]
    ytr, yte = tr.is_fraud.values, te.is_fraud.values
    print(f"train {len(tr)} ({ytr.sum()} fraud) | test {len(te)} ({yte.sum()} fraud)")

    rows = []
    # (1) rules only
    rs_te = np.array([rule_score(r)[0] for r in te.to_dict("records")])
    rows.append(summarize(yte, rs_te, "rules only"))
    # (2) GBM on behavioural features only
    mb, _ = train_gbm(tr, ytr, BEHAV_COLS)
    rows.append(summarize(yte, mb.predict_proba(te[BEHAV_COLS])[:, 1], "GBM behavioural features"))
    # (3) GBM on all features (behavioural + graph + drift)
    m, backend = train_gbm(tr, ytr, FEATURE_COLS)
    p_te = m.predict_proba(te[FEATURE_COLS])[:, 1]
    rows.append(summarize(yte, p_te, f"GBM all features ({backend})"))
    # (4) GBM + rules (noisy-OR)
    combo = 1 - (1 - p_te) * (1 - rs_te)
    rows.append(summarize(yte, combo, "GBM ⊕ rules (noisy-OR)"))
    res = pd.DataFrame(rows)

    # per-scenario recall at 1 % FPR for the all-feature model
    _, thr = recall_at_fpr(yte, p_te, 0.01)
    te2 = te.assign(p=p_te, caught=p_te > thr)
    per_scen = te2[te2.is_fraud == 1].groupby("scenario")["caught"].agg(["mean", "size"]).rename(columns={"mean": "recall@1%FPR", "size": "n"})
    prevented = te2[(te2.is_fraud == 1) & te2.caught].charge_inr.sum() * 1.6
    total_loss = te2[te2.is_fraud == 1].charge_inr.sum() * 1.6
    fp = int(((te2.is_fraud == 0) & te2.caught).sum())

    # feature importance
    if backend == "lightgbm":
        imp = pd.Series(m.booster_.feature_importance("gain"), index=FEATURE_COLS).sort_values(ascending=False)
        contrib = m.booster_.predict(te[FEATURE_COLS], pred_contrib=True)
    else:
        imp = pd.Series(getattr(m, "feature_importances_", np.zeros(len(FEATURE_COLS))), index=FEATURE_COLS).sort_values(ascending=False)
        contrib = None

    # example evidence pack for the highest-scoring caught fraud
    idx = int(np.argmax(np.where(yte == 1, p_te, -1)))
    ex = te.iloc[idx]
    evidence = dict(booking_id=ex.booking_id, shipper_id=ex.shipper_id, scenario=ex.scenario,
                    p_fraud=float(p_te[idx]), rule_hits=rule_score(ex.to_dict())[1])
    if contrib is not None:
        c = pd.Series(contrib[idx][:-1], index=FEATURE_COLS).sort_values(key=abs, ascending=False)
        evidence["top_contributions"] = [dict(feature=k, value=float(ex[k]), contribution=float(v)) for k, v in c.head(8).items()]
    (HERE / "example_evidence.json").write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    with open(HERE / "model.pkl", "wb") as fh:
        pickle.dump(dict(model=m, backend=backend, feature_cols=FEATURE_COLS, threshold_fpr1=thr), fh)

    md = ["# Experiment A — rules + GBM + attributions", "",
          f"Stream: {len(df)} bookings, {df.is_fraud.sum()} fraud ({df.is_fraud.mean():.2%}). "
          f"Time split at {cut.date()}: train {len(tr)} / test {len(te)} ({yte.sum()} fraud in test).", "",
          "## Ranking quality (test period)", "",
          res.to_markdown(index=False, floatfmt=".3f"), "",
          "`recall_fpr1` = share of fraud caught when at most 1 % of legitimate bookings are flagged.", "",
          "## Per-scenario recall at 1 % FPR (all-feature GBM)", "",
          per_scen.to_markdown(floatfmt=".2f"), "",
          f"Loss prevented at 1 % FPR: ₹{prevented:,.0f} of ₹{total_loss:,.0f} at risk "
          f"({prevented / total_loss:.0%}); {fp} legitimate bookings flagged out of {(yte == 0).sum()}.", "",
          "## Top features by gain", "", imp.head(15).to_frame("gain").to_markdown(floatfmt=".0f"), "",
          "## Observations", "",
          "- Rules alone have high precision on the loud scenarios but miss the stealthy ones; they earn their keep as",
          "  *hard blocks with reason codes* and as a safety net when the model is unavailable, not as the main detector.",
          "- Adding graph + drift features to the behavioural GBM is where the stealthy-mule and payment-swap",
          "  scenarios move (compare the two GBM rows and the per-scenario table).",
          "- Attributions come from LightGBM's native `pred_contrib` (exact TreeSHAP values); no extra dependency.",
          "- Profile poisoning: once the first fraudulent booking of a burst is absorbed into the shipper profile, later",
          "  bookings of the same burst look 'seen'. The pipeline fixes this by quarantining held/blocked bookings from",
          "  the profile until they are verified (see prototypes/fraudshield-pipeline).", ""]
    (HERE / "results.md").write_text("\n".join(md), encoding="utf-8")
    print(res.to_string(index=False))
    print(per_scen)
    print(f"prevented ₹{prevented:,.0f} / ₹{total_loss:,.0f}")


if __name__ == "__main__":
    main()
