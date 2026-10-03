"""Train the DataCo FraudShield model once and save it to models/dataco/.

    python prototypes/fraudshield-pipeline/train_dataco.py

Trains on 2015–2016, calibrates and fits the conformal set on 2017-H1 (DataCoShield.fit), evaluates
on the untouched test window (2017-07 → 2018-01), then writes
    models/dataco/fraudshield_dataco.pkl   fitted model, category codes, calibrator, conformal set, thresholds
    models/dataco/metadata.json            versions, features, training sizes, test metrics
api_dataco.py loads this file at start-up instead of retraining.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "prototypes" / "data"))
import dataco_features as F                   # noqa: E402
import dataco_protocol as P                   # noqa: E402
from fraudshield.dataco import DataCoShield   # noqa: E402

MODEL_DIR = ROOT / "models" / "dataco"


def main():
    o = F.cached_orders()
    shield = DataCoShield().fit(o)
    _, _, te = F.split(o)
    p = shield.model.predict_proba(shield.coder.transform(te))
    ev = P.evaluate(te, p)
    test = {scope: {k: (list(v) if isinstance(v, tuple) else v) for k, v in ev[scope].items()} for scope in ev}
    path = shield.save(MODEL_DIR, metadata=dict(
        trained_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), splits=F.SPLITS, test_metrics=test,
        note="Inside TRANSFER orders the ranking is close to chance; see notes/comparison-dataco.md."))
    print(f"saved {path} ({path.stat().st_size / 1e6:.1f} MB), model {shield.model.version}")
    print(f"test ROC-AUC all orders {ev['all']['roc_auc']:.3f}, inside TRANSFER {ev['transfer']['roc_auc']:.3f}")

    again = DataCoShield.load(MODEL_DIR)
    same = np.allclose(again.model.predict_proba(again.coder.transform(te)), p)
    print("reload check: predictions identical =", same)
    if not same:
        raise SystemExit("reloaded model does not reproduce the predictions")


if __name__ == "__main__":
    main()
