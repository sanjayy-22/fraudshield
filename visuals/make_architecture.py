"""Generates visuals/architecture.svg and visuals/architecture.html — the FraudShield
target pipeline architecture as a layered diagram (sources → ingestion → feature
platform → detection ensemble → decision → actions, with the async explanation, audit
and feedback services alongside).

    python3 make_architecture.py
"""
from __future__ import annotations

import html
from pathlib import Path

W, H = 1500, 1010
LEFT_W = 1090
RIGHT_X = LEFT_W + 40
RIGHT_W = W - RIGHT_X - 20

# palette (light / dark handled by CSS variables inside the SVG)
LANES = [
    # (title, y, height, [boxes: (label, sublabel, x, w)])
    ("1 · SOURCES", 20, 78, [
        ("Booking API / UI", "sync scoring call", 20, 200),
        ("Account master (MDM)", "CDC stream", 232, 200),
        ("Payment gateway", "instrument events", 444, 200),
        ("Device / session telemetry", "fingerprint, IP, geo", 656, 200),
        ("Delivery & case outcomes", "post-delivery fraud labels", 868, 202)]),
    ("2 · INGESTION", 118, 78, [
        ("Kafka topics: booking.created · entity.updated · label.confirmed", "schema registry · partitioned by shipper_id · idempotent consumers", 20, 640),
        ("Sync REST/gRPC scoring endpoint", "SLA p99 < 150 ms · fail-safe mode by value", 672, 398)]),
    ("3 · FEATURE PLATFORM (point-in-time correct, one definition online + offline)", 216, 120, [
        ("Shipper behavioural profile", "Bayesian per-shipper stats · cohort back-off", 20, 255),
        ("Velocity counters", "1 h / 24 h / 7 d vs baseline", 287, 190),
        ("Entity-graph counters", "fan-in per entity · capped components · fraud density", 489, 300),
        ("Identity & account", "device / instrument novelty & age, dormancy", 801, 269),
        ("Online store: Redis / Feast", "", 20, 520),
        ("Offline store: warehouse / Parquet · same feature code, replayed", "", 552, 518)]),
    ("4 · DETECTION ENSEMBLE (parallel, < 30 ms)", 356, 122, [
        ("Rules engine", "versioned · reason codes · hard blocks", 20, 240),
        ("Supervised GBM", "LightGBM, all families · TreeSHAP attributions", 272, 255),
        ("Behavioural drift", "unsupervised deviation · label-free fallback", 539, 250),
        ("Entity-graph signals", "mule / ring detection · label propagation", 801, 269),
        ("Calibration (Platt) → fraud probability p  ·  Mondrian conformal → prediction set {legit | fraud | both}", "", 20, 1050)]),
    ("5 · DECISION ENGINE", 498, 86, [
        ("Expected-cost policy:  argmin { p·L,  (1−p)·C_block,  E[step-up],  E[hold] }", "inputs: p, charge, ops cost, customer LTV, analyst capacity, conformal ambiguity, hard rules · versioned", 20, 730),
        ("ALLOW", "", 758, 60), ("STEP-UP", "OTP · call-back", 824, 112), ("HOLD", "analyst", 942, 66), ("BLOCK", "", 1014, 62)]),
    ("6 · ACTIONS & INTEGRATION", 604, 78, [
        ("Booking system callback", "accept / hold / reject status", 20, 240),
        ("Verification workflow", "step-up outcome = instant label", 272, 240),
        ("Analyst case queue", "priority by expected loss", 524, 240),
        ("Ops workflow", "hold at pickup / first scan", 776, 294)]),
]
RIGHT = [
    ("GENAI EXPLANATION SERVICE (async)", 20, 300, [
        "evidence pack: SHAP top-k · rule hits · graph facts · drift stats · counterfactual",
        "LLM narrates the pack only (analyst + customer variants)",
        "grounding verifier: every number / id must exist in the pack, else reject",
        "cached per decision id; never on the booking-time path"]),
    ("AUDIT & COMPLIANCE", 340, 200, [
        "append-only hash-chained decision ledger: features, versions, scores, action",
        "deterministic replay of any decision",
        "model registry (MLflow) · policy & rule versions · PII minimisation"]),
    ("FEEDBACK & LEARNING", 560, 230, [
        "labels: step-up outcomes (hours) · analyst decisions (hours) · post-delivery (days)",
        "profile quarantine: unverified bookings never update the baseline",
        "drift monitoring (PSI) · scheduled retrain · champion / challenger shadow scoring",
        "rule mining from confirmed cases → proposed rules for analyst sign-off"]),
    ("DASHBOARD", 810, 150, [
        "fraud attempts vs stopped · prevented loss · friction rate",
        "action mix by cohort · review queue SLA · model & policy health · ring views"]),
]


def box(x, y, w, h, label, sub="", cls="box"):
    lines = [f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/>',
             f'<text class="lbl" x="{x + 10}" y="{y + 20}">{html.escape(label)}</text>']
    if sub:
        lines.append(f'<text class="sub" x="{x + 10}" y="{y + 38}">{html.escape(sub)}</text>')
    return "\n".join(lines)


def wrap(text, width=78):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    return lines + [cur]


def build() -> str:
    out = []
    for title, y, h, boxes in LANES:
        out.append(f'<rect class="lane" x="10" y="{y}" width="{LEFT_W}" height="{h}" rx="10"/>')
        out.append(f'<text class="lane-title" x="20" y="{y + 16}">{html.escape(title)}</text>')
        for label, sub, x, w in boxes:
            by = y + 24
            bh = 44 if sub else 24
            if title.startswith("3") and label.startswith(("Online", "Offline")):
                by = y + 88; bh = 24
            if title.startswith("4") and label.startswith("Calibration"):
                by = y + 88; bh = 24
            if title.startswith("5") and label in ("ALLOW", "STEP-UP", "HOLD", "BLOCK"):
                cls = {"ALLOW": "act-allow", "STEP-UP": "act-step", "HOLD": "act-hold", "BLOCK": "act-block"}[label]
                out.append('<g class="act">' + box(x + 10, by, w, 44 if sub else 24, label, sub, cls) + '</g>')
                continue
            out.append(box(x + 10, by, w, bh, label, sub))
    # flow arrows between lanes
    for i in range(len(LANES) - 1):
        y0 = LANES[i][1] + LANES[i][2]; y1 = LANES[i + 1][1]
        for x in (300, 560, 820):
            out.append(f'<line class="arrow" x1="{x}" y1="{y0}" x2="{x}" y2="{y1}" marker-end="url(#ah)"/>')
    # right column
    for title, y, h, items in RIGHT:
        out.append(f'<rect class="lane side" x="{RIGHT_X}" y="{y}" width="{RIGHT_W}" height="{h}" rx="10"/>')
        out.append(f'<text class="lane-title" x="{RIGHT_X + 12}" y="{y + 18}">{html.escape(title)}</text>')
        yy = y + 40
        for it in items:
            for k, line in enumerate(wrap(it, 52)):
                prefix = "• " if k == 0 else "   "
                out.append(f'<text class="item" x="{RIGHT_X + 14}" y="{yy}">{html.escape(prefix + line)}</text>')
                yy += 16
            yy += 6
    # dashed links: ensemble/decision → explanation & audit ; actions → feedback ; feedback → features
    out.append(f'<path class="dash" d="M {LEFT_W + 10} 540 L {RIGHT_X} 160" marker-end="url(#ah)"/>')
    out.append(f'<path class="dash" d="M {LEFT_W + 10} 560 L {RIGHT_X} 440" marker-end="url(#ah)"/>')
    out.append(f'<path class="dash" d="M {LEFT_W + 10} 660 L {RIGHT_X} 660" marker-end="url(#ah)"/>')
    out.append(f'<path class="dash" d="M {RIGHT_X} 700 C 1080 760, 900 760, 800 700 L 20 700 L 20 300 L 12 300" marker-end="url(#ah)"/>')
    out.append(f'<text class="note" x="30" y="{H - 14}">Synchronous booking path: lanes 2 → 3 → 4 → 5 → 6 (target p99 &lt; 150 ms end-to-end; prototype measures ~3 ms p99 for lanes 3–5 in one process). Everything on the right runs asynchronously.</text>')
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif">
<style>
  :root {{ --bg:#fcfcfb; --lane:#f0efec; --side:#e8eef8; --box:#ffffff; --stroke:#c9c8c3; --ink:#0b0b0b; --ink2:#52514e; --arrow:#8a8984;
           --allow:#0ca30c; --step:#2a78d6; --hold:#eda100; --block:#d03b3b; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#1a1a19; --lane:#262624; --side:#22303f; --box:#2f2f2d; --stroke:#4a4946; --ink:#ffffff; --ink2:#c3c2b7; --arrow:#8f8e86; }} }}
  .bg {{ fill:var(--bg); }} .lane {{ fill:var(--lane); }} .side {{ fill:var(--side); }}
  .box {{ fill:var(--box); stroke:var(--stroke); stroke-width:1; }}
  .lbl {{ font-size:13px; font-weight:600; fill:var(--ink); }} .sub {{ font-size:11px; fill:var(--ink2); }}
  .lane-title {{ font-size:12px; font-weight:700; letter-spacing:.04em; fill:var(--ink2); }}
  .item {{ font-size:12px; fill:var(--ink); }} .note {{ font-size:12px; fill:var(--ink2); }}
  .arrow {{ stroke:var(--arrow); stroke-width:1.5; }} .dash {{ stroke:var(--arrow); stroke-width:1.5; fill:none; stroke-dasharray:6 5; }}
  .act-allow {{ fill:var(--allow); stroke:none; }} .act-step {{ fill:var(--step); stroke:none; }} .act-hold {{ fill:var(--hold); stroke:none; }} .act-block {{ fill:var(--block); stroke:none; }}
  .act .lbl, .act .sub {{ fill:#fff; }}
</style>
<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--arrow)"/></marker></defs>
<rect class="bg" width="{W}" height="{H}"/>
<text class="lbl" x="20" y="{H - 34}" font-size="15">FraudShield — booking-time fraud detection pipeline (target architecture)</text>
{chr(10).join(out)}
</svg>"""
    return svg


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    svg = build()
    (here / "architecture.svg").write_text(svg, encoding="utf-8")
    (here / "architecture.html").write_text(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>FraudShield architecture</title><style>body{margin:0;background:#fcfcfb}@media(prefers-color-scheme:dark){body{background:#1a1a19}}"
        "svg{width:100%;height:auto;display:block;max-width:1500px;margin:0 auto}</style></head><body>" + svg + "</body></html>",
        encoding="utf-8",
    )
    print("wrote architecture.svg / architecture.html")
