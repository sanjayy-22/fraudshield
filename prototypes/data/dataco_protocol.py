"""Shared evaluation protocol for every DataCo experiment (e0–e5).

* Time split from `dataco_features.SPLITS` (train 2015–2016, valid 2017-H1, test 2017-07 → 2018-01).
* One row per order; an order never appears in two splits.
* Metrics on the test split, reported for two scopes:
    all       every order
    transfer  TRANSFER orders only. Every fraud in DataCo is a TRANSFER order, so this scope
              shows whether a model learned anything beyond the payment-type rule.
* PR-AUC is the headline metric (positives are rare). 95 % bootstrap intervals (order resampling)
  are given for ROC-AUC and PR-AUC, so "better than chance" is a claim with an error bar.
* recall@FPR uses the threshold that gives that false-positive rate on the scored set itself
  (an oracle threshold), so it measures ranking quality, not a deployable operating point. A fraud
  counts only if its score is strictly above that threshold, so coarse or binary scores (the E1 rule)
  get 0 when ties straddle the threshold.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

try:
    import lightgbm as lgb
except ImportError:      # pragma: no cover
    lgb = None

N_BOOT = 300
warnings.filterwarnings("ignore", message=".*eval_set.*deprecated.*")


def recall_at_fpr(y: np.ndarray, s: np.ndarray, fpr: float) -> float:
    neg = np.sort(s[y == 0])[::-1]
    if len(neg) == 0 or y.sum() == 0:
        return float("nan")
    thr = neg[min(int(np.floor(fpr * len(neg))), len(neg) - 1)]
    return float((s[y == 1] > thr).mean())


def _boot_ci(y: np.ndarray, s: np.ndarray, fn, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(N_BOOT):
        i = rng.integers(0, len(y), len(y))
        if 0 < y[i].sum() < len(i):
            vals.append(fn(y[i], s[i]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def score_block(y: np.ndarray, s: np.ndarray) -> dict:
    y, s = np.asarray(y).astype(int), np.asarray(s).astype(float)
    base = float(y.mean())
    roc, pr = roc_auc_score(y, s), average_precision_score(y, s)
    return dict(
        n=int(len(y)), fraud=int(y.sum()), base_rate=base,
        roc_auc=float(roc), roc_ci=_boot_ci(y, s, roc_auc_score),
        pr_auc=float(pr), pr_ci=_boot_ci(y, s, average_precision_score), pr_lift=float(pr / base),
        rec_1=recall_at_fpr(y, s, 0.01), rec_5=recall_at_fpr(y, s, 0.05),
    )


def evaluate(test: pd.DataFrame, score: np.ndarray) -> dict:
    score = np.asarray(score, dtype=float)
    tr = (test.payment_type == "TRANSFER").values
    return {"all": score_block(test.is_fraud.values, score),
            "transfer": score_block(test.is_fraud.values[tr], score[tr])}


# ------------------------------------------------------------------ the shared GBM
def train_gbm(Xtr: pd.DataFrame, ytr: np.ndarray, Xva: pd.DataFrame, yva: np.ndarray, seed: int = 1):
    """LightGBM, deliberately small (rare positives), early-stopped on validation PR-AUC."""
    pos = max(int(ytr.sum()), 1)
    m = lgb.LGBMClassifier(
        n_estimators=2000, learning_rate=0.03, num_leaves=15, min_child_samples=40,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0,
        scale_pos_weight=min((len(ytr) - pos) / pos, 20.0), verbose=-1, random_state=seed)
    m.fit(Xtr, ytr, eval_set=[(Xva, yva)], eval_metric="average_precision",
          callbacks=[lgb.early_stopping(100, first_metric_only=True, verbose=False)])
    return m


def importance(model, cols: list[str], X: pd.DataFrame | None = None) -> pd.DataFrame:
    """Gain importance, plus mean |TreeSHAP| on X when given."""
    out = pd.DataFrame({"feature": cols, "gain": model.booster_.feature_importance("gain")})
    out["gain_share"] = out.gain / max(out.gain.sum(), 1e-12)
    if X is not None:
        contrib = model.booster_.predict(X, pred_contrib=True)[:, :-1]
        out["mean_abs_shap"] = np.abs(contrib).mean(axis=0)
    return out.sort_values("gain", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------ reporting
def _fmt_ci(v: float, ci: tuple[float, float]) -> str:
    return f"{v:.3f} [{ci[0]:.3f}, {ci[1]:.3f}]"


def metrics_table(rows: dict[str, dict]) -> str:
    """rows: label -> evaluate() output. Markdown table, one line per (label, scope)."""
    head = ("| model | scope | orders | fraud | base rate | ROC-AUC [95% CI] | PR-AUC [95% CI] | PR lift "
            "| recall @1% FPR | recall @5% FPR |\n|---|---|---:|---:|---:|---|---|---:|---:|---:|")
    lines = [head]
    for label, ev in rows.items():
        for scope in ("all", "transfer"):
            b = ev[scope]
            lines.append(f"| {label} | {scope} | {b['n']} | {b['fraud']} | {b['base_rate']:.4f} | "
                         f"{_fmt_ci(b['roc_auc'], b['roc_ci'])} | {_fmt_ci(b['pr_auc'], b['pr_ci'])} | "
                         f"{b['pr_lift']:.2f}× | {b['rec_1']:.3f} | {b['rec_5']:.3f} |")
    return "\n".join(lines)


def importance_table(imp: pd.DataFrame, k: int = 12) -> str:
    cols = ["feature", "gain_share"] + (["mean_abs_shap"] if "mean_abs_shap" in imp else [])
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in imp.head(k).iterrows():
        lines.append("| " + " | ".join(f"{r[c]:.4f}" if isinstance(r[c], float) else str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def split_summary(o: pd.DataFrame) -> str:
    g = o.groupby("split").agg(start=("ts", "min"), end=("ts", "max"), orders=("is_fraud", "size"),
                               fraud=("is_fraud", "sum"))
    lines = ["| split | from | to | orders | fraud orders |", "|---|---|---|---:|---:|"]
    for s in ("train", "valid", "test"):
        r = g.loc[s]
        lines.append(f"| {s} | {r.start:%Y-%m-%d} | {r.end:%Y-%m-%d} | {r.orders} | {r.fraud} |")
    return "\n".join(lines)


def write(path: Path, text: str) -> None:
    Path(path).write_text(text.strip() + "\n", encoding="utf-8")
    print(f"wrote {path}")
