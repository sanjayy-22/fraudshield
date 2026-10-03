"""Path setup + shared helpers for the DataCo experiments (e0–e5)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prototypes" / "data"))

import dataco_features as F  # noqa: E402,F401
import dataco_protocol as P  # noqa: E402,F401


def save_scores(folder: Path, payload: dict) -> None:
    """Machine-readable results (metrics + test scores) for notes/ and visuals/."""
    (folder / "scores.json").write_text(json.dumps(payload, default=float), encoding="utf-8")
