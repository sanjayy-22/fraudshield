"""Append-only, hash-chained decision ledger with deterministic replay.

Every decision writes one JSON line: the exact feature vector that was scored, the
versions of the feature definitions, model, rules and policy, the scores, the action,
and the hash of the previous record. Tampering with or deleting any record breaks the
chain. `replay()` re-scores a stored feature vector with the stored model version and
checks that the recorded probability is reproduced — the "explainable, traceable,
reviewable" requirement made mechanical.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class AuditLedger:
    GENESIS = "0" * 64

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.prev_hash = self.GENESIS
        self.count = 0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                self.prev_hash, self.count = rec["hash"], self.count + 1
        else:
            self.path.write_text("", encoding="utf-8")

    def append(self, record: dict) -> str:
        body = dict(record, seq=self.count, prev_hash=self.prev_hash)
        h = hashlib.sha256((self.prev_hash + _canonical(body)).encode()).hexdigest()
        body["hash"] = h
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(_canonical(body) + "\n")
        self.prev_hash, self.count = h, self.count + 1
        return h

    def records(self):
        for line in self.path.read_text(encoding="utf-8").splitlines():
            yield json.loads(line)

    def verify(self) -> tuple[bool, int]:
        prev, n = self.GENESIS, 0
        for rec in self.records():
            h = rec.pop("hash")
            if rec.get("prev_hash") != prev:
                return False, n
            if hashlib.sha256((prev + _canonical(rec)).encode()).hexdigest() != h:
                return False, n
            prev, n = h, n + 1
        return True, n

    def get(self, booking_id: str) -> dict | None:
        for rec in self.records():
            if rec.get("booking_id") == booking_id:
                return rec
        return None

    def replay(self, booking_id: str, model) -> dict:
        rec = self.get(booking_id)
        if rec is None:
            return dict(found=False)
        p = model.predict_one(rec["features"])
        return dict(found=True, stored_p=rec["p_fraud"], replayed_p=p,
                    same_model=(rec["model_version"] == model.version),
                    reproduced=abs(p - rec["p_fraud"]) < 1e-9)
