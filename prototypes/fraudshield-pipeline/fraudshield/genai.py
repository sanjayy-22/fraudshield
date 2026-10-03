"""Plain-language AI explanations of a booking decision, for people who are not fraud experts.

1. `evidence(booking)`: a fixed pack of facts (decision, overall risk, each matched rule with its plain meaning,
   weight and the risk before → after, the thresholds, and the model's top reasons).
2. `ask_llm(evidence)`: OpenRouter chat completion. The model is told to use only these facts.
3. `check_numbers(text, evidence)`: every number in the AI text must appear in the evidence. If it doesn't, or
   there is no key, a timeout or a network error, the template explanation (written from the same facts) is used,
   and the result says so.

Configuration (never committed): OPENROUTER_API_KEY and OPENROUTER_MODEL, from the environment or from the
git-ignored `.env` file at the repository root. See `.env.example`.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "qwen/qwen3.8-27b:free"
ROOT = Path(__file__).resolve().parents[3]
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
STATUS_WORDS = {"CONFIRMED": "approved and shipped", "VERIFICATION_REQUIRED": "waiting for the customer to verify",
                "UNDER_REVIEW": "waiting for a person on the fraud team to check it", "BLOCKED": "stopped and not shipped"}
ACTION_WORDS = {"ALLOW": "approve", "STEP_UP": "ask the customer to verify", "HOLD": "send it to team review",
                "BLOCK": "stop it"}


def _env(name: str, default: str | None = None) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


# ------------------------------------------------------------------ evidence
def evidence(b, thresholds: dict) -> dict:
    return dict(
        order=f"{b.booking_id.replace('dataco-', '#')}, ${float(b.order['net_total']):,.2f} to {b.order['order_city']}, {b.order['order_country']}",
        payment=b.order["payment_type"],
        decision=ACTION_WORDS[b.decision["action"]],
        status=STATUS_WORDS[b.status] + (" (confirmed fraud)" if b.confirmed_fraud else ""),
        decided_by=b.decided_by,
        ai_model_risk=_pct(b.model_risk),
        overall_risk=_pct(b.overall_risk),
        rules=[dict(name=h["name"], meaning=h["plain"], weight=f"{h['weight'] * 100:.0f}%", hard=h["hard"],
                    risk_before=_pct(h["before"]), risk_after=_pct(h["after"])) for h in b.rules_matched],
        thresholds=dict(verify=f"{thresholds['verify'] * 100:.0f}%", team_review=f"{thresholds['review'] * 100:.0f}%",
                        stop_as_fraud=f"{thresholds['stop'] * 100:.0f}%"),
        how_rules_add="each rule adds its weight times the risk that is left: new = old + (100% - old) x weight",
        model_reasons=[r["label"] for r in b.reasons[:3]],
    )


def template(ev: dict) -> str:
    parts = [f"Order {ev['order']} is {ev['status']}."]
    if ev["rules"]:
        parts.append(f"The AI model alone rated it {ev['ai_model_risk']} risky.")
        for r in ev["rules"]:
            hard = " This rule always stops an order." if r["hard"] else ""
            parts.append(f"Rule \"{r['name']}\" matched ({r['weight']}): {r['meaning']} Risk went from "
                         f"{r['risk_before']} to {r['risk_after']}.{hard}")
    else:
        parts.append(f"No fraud rule matched; the AI model rated it {ev['ai_model_risk']} risky.")
    t = ev["thresholds"]
    parts.append(f"Overall risk: {ev['overall_risk']}. From {t['verify']} we ask the customer to verify, from "
                 f"{t['team_review']} a person checks it, and from {t['stop_as_fraud']} we treat it as fraud and stop it.")
    return " ".join(parts)


# ------------------------------------------------------------------ LLM
SYSTEM = ("You explain fraud-check decisions to hackathon judges who are not technical. Use simple words and short "
          "sentences. Use ONLY the facts in the JSON you are given. Never invent numbers, names or reasons. "
          "Write one paragraph of at most 120 words, no lists, no markdown.")


def prompt(ev: dict) -> str:
    return ("Explain this decision. Say what happened to the order, name each matched rule and what it means in "
            "everyday words with its percentage, show how the risk added up to the overall risk, and say from what "
            "minimum percentage we stop an order as fraud.\n\nFACTS:\n" + json.dumps(ev, ensure_ascii=False))


def ask_llm(ev: dict, timeout: float = 25.0) -> tuple[str | None, str]:
    key = _env("OPENROUTER_API_KEY")
    model = _env("OPENROUTER_MODEL", DEFAULT_MODEL)
    if not key:
        return None, "no OPENROUTER_API_KEY set"
    body = json.dumps(dict(model=model, temperature=0.2, max_tokens=400, reasoning=dict(exclude=True),
                           messages=[dict(role="system", content=SYSTEM), dict(role="user", content=prompt(ev))])).encode()
    req = urllib.request.Request(_env("OPENROUTER_URL", DEFAULT_ENDPOINT), data=body, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/sanjayy-22/fraudshield", "X-Title": "FraudShield"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        return None, f"provider returned HTTP {e.code}: {detail}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, f"could not reach the AI provider ({e.__class__.__name__}: {getattr(e, 'reason', e)})"
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return None, "unexpected reply from the AI provider"
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    return (text or None), (model if text else "empty reply from the AI provider")


def _numbers(s: str) -> set[float]:
    return {round(float(n.replace(",", "")), 1) for n in NUM_RE.findall(s)}


def check_numbers(text: str, ev: dict) -> list[str]:
    """Numbers in the AI text that do not appear in the evidence (100 is allowed: '100% − old')."""
    allowed = _numbers(json.dumps(ev, ensure_ascii=False)) | {100.0}
    return sorted({n for n in NUM_RE.findall(text) if round(float(n.replace(",", "")), 1) not in allowed})


def explain(b, thresholds: dict, use_llm: bool = True) -> dict:
    ev = evidence(b, thresholds)
    base = dict(evidence=ev, template=template(ev))
    if not use_llm:
        return dict(base, text=base["template"], source="template", note="AI explanation turned off")
    text, info = ask_llm(ev)
    if text is None:
        return dict(base, text=base["template"], source="template", note=info)
    bad = check_numbers(text, ev)
    if bad:
        return dict(base, text=base["template"], source="template", rejected_ai_text=text,
                    note=f"AI text rejected: it used numbers not in the facts ({', '.join(bad)})")
    return dict(base, text=text, source="ai", model=info, note="written by AI from the facts above; every number checked")
