"""Static HTML dashboard for the FraudShield replay (no external dependencies).

Renders plain HTML + inline SVG from stats.json: stat tiles, a daily fraud-vs-stopped
line chart, policy-cost bars, action mix by cohort, scenario recall, the top-scored
bookings and the audit-ledger status. Colors follow a validated categorical order and
are declared as CSS roles with a selected dark mode.
"""
from __future__ import annotations

import html
import json

SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500"]
STATUS = dict(good="#0ca30c", warning="#fab219", serious="#ec835a", critical="#d03b3b")
ACTIONS = ["ALLOW", "STEP_UP", "HOLD", "BLOCK"]


def _fmt_inr(v: float) -> str:
    return f"₹{v:,.0f}"


def _line_chart(days: list[dict], w=900, h=260) -> str:
    """Daily fraud attempts vs stopped — two lines, legend, hover tooltips, table fallback."""
    if not days:
        return ""
    ml, mr, mt, mb = 40, 16, 16, 34
    n = len(days)
    ymax = max(max(d["fraud"] for d in days), 1)
    xs = [ml + i * (w - ml - mr) / max(n - 1, 1) for i in range(n)]

    def y(v):
        return mt + (h - mt - mb) * (1 - v / ymax)

    def path(key):
        return "M" + " L".join(f"{xs[i]:.1f},{y(d[key]):.1f}" for i, d in enumerate(days))

    grid = "".join(f'<line class="grid" x1="{ml}" x2="{w - mr}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="tick" x="{ml - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{t}</text>'
                   for t in sorted({0, ymax // 2, ymax}))
    ticks = "".join(f'<text class="tick" x="{xs[i]:.1f}" y="{h - 12}" text-anchor="middle">{days[i]["day"][5:]}</text>'
                    for i in range(0, n, max(n // 6, 1)))
    dots = "".join(
        f'<g class="pt"><circle cx="{xs[i]:.1f}" cy="{y(d["fraud"]):.1f}" r="9" fill="transparent">'
        f'<title>{d["day"]}: {d["fraud"]} fraud attempts, {d["stopped"]} stopped before shipping, {d["legit"]} legitimate bookings, {d["friction"]} asked to verify / held / blocked</title></circle>'
        f'<circle cx="{xs[i]:.1f}" cy="{y(d["stopped"]):.1f}" r="3.5" class="s2 ring"/>'
        f'<circle cx="{xs[i]:.1f}" cy="{y(d["fraud"]):.1f}" r="3.5" class="s1 ring"/></g>'
        for i, d in enumerate(days))
    table = "".join(f"<tr><td>{d['day']}</td><td>{d['fraud']}</td><td>{d['stopped']}</td><td>{d['legit']}</td><td>{d['friction']}</td></tr>" for d in days)
    return f"""
<figure>
<figcaption><strong>Fraud attempts per day vs stopped before shipping</strong> <span class="legend"><i class="sw s1"></i>attempts <i class="sw s2"></i>stopped</span></figcaption>
<svg viewBox="0 0 {w} {h}" role="img" aria-label="daily fraud attempts and stopped">
{grid}{ticks}
<path d="{path('fraud')}" class="line s1"/><path d="{path('stopped')}" class="line s2"/>
{dots}
</svg>
<details><summary>table view</summary><table><thead><tr><th>day</th><th>fraud attempts</th><th>stopped</th><th>legit</th><th>legit with friction</th></tr></thead><tbody>{table}</tbody></table></details>
</figure>"""


def _hbar(rows: list[tuple[str, float, str]], title: str, fmt=lambda v: f"{v:,.0f}", w=900, cls="s1") -> str:
    """Single-series horizontal bars with direct labels and hover tooltips."""
    if not rows:
        return ""
    vmax = max(v for _, v, _ in rows) or 1
    bh, gap, lw = 26, 10, 300
    h = len(rows) * (bh + gap) + 10
    bars = ""
    for i, (label, v, tip) in enumerate(rows):
        yy = 5 + i * (bh + gap)
        bw = (w - lw - 90) * v / vmax
        bars += (f'<g class="bar"><title>{html.escape(tip)}</title>'
                 f'<text class="lbl" x="{lw - 10}" y="{yy + bh / 2 + 4}" text-anchor="end">{html.escape(label)}</text>'
                 f'<rect class="{cls}" x="{lw}" y="{yy}" width="{max(bw, 2):.1f}" height="{bh}" rx="4"/>'
                 f'<text class="val" x="{lw + bw + 8:.1f}" y="{yy + bh / 2 + 4}">{fmt(v)}</text></g>')
    return f'<figure><figcaption><strong>{html.escape(title)}</strong></figcaption><svg viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(title)}">{bars}</svg></figure>'


def _stacked(by_cohort: dict, w=900, title: str = "Live decisions by customer cohort") -> str:
    """Action mix per cohort — stacked 100 % bars, 2px surface gap, legend + tooltips."""
    bh, gap, lw = 28, 12, 120
    h = len(by_cohort) * (bh + gap) + 10
    out = ""
    for i, (cohort, counts) in enumerate(by_cohort.items()):
        total = sum(counts.values()) or 1
        x, yy = lw, 5 + i * (bh + gap)
        out += f'<text class="lbl" x="{lw - 10}" y="{yy + bh / 2 + 4}" text-anchor="end">{cohort}</text>'
        for j, a in enumerate(ACTIONS):
            seg = (w - lw - 20) * counts.get(a, 0) / total
            if seg <= 0:
                continue
            out += (f'<rect class="s{j + 1} seg" x="{x + 1:.1f}" y="{yy}" width="{max(seg - 2, 0):.1f}" height="{bh}" rx="3">'
                    f'<title>{cohort}: {a} {counts.get(a, 0)} ({100 * counts.get(a, 0) / total:.1f}%)</title></rect>')
            if seg > 60:
                out += f'<text class="val on" x="{x + seg / 2:.1f}" y="{yy + bh / 2 + 4}" text-anchor="middle">{a} {100 * counts.get(a, 0) / total:.0f}%</text>'
            x += seg
    legend = "".join(f'<i class="sw s{j + 1}"></i>{a} ' for j, a in enumerate(ACTIONS))
    return (f'<figure><figcaption><strong>{html.escape(title)}</strong> <span class="legend">{legend}</span></figcaption>'
            f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="action mix by cohort">{out}</svg></figure>')


def base_css() -> str:
    """Shared page CSS: color roles, selected dark mode, tiles, charts, tables."""
    return f"""
:root {{ color-scheme: light; --surface:#fcfcfb; --surface-2:#f0efec; --ink:#0b0b0b; --ink-2:#52514e; --ink-3:#8a8984; --grid:#e3e2de;
  --s1:{SERIES_LIGHT[0]}; --s2:{SERIES_LIGHT[1]}; --s3:{SERIES_LIGHT[2]}; --s4:{SERIES_LIGHT[3]}; --good:{STATUS['good']}; --critical:{STATUS['critical']}; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ color-scheme: dark; --surface:#1a1a19; --surface-2:#262624; --ink:#fff; --ink-2:#c3c2b7; --ink-3:#8f8e86; --grid:#383835;
  --s1:{SERIES_DARK[0]}; --s2:{SERIES_DARK[1]}; --s3:{SERIES_DARK[2]}; --s4:{SERIES_DARK[3]}; }} }}
:root[data-theme="dark"] {{ color-scheme: dark; --surface:#1a1a19; --surface-2:#262624; --ink:#fff; --ink-2:#c3c2b7; --ink-3:#8f8e86; --grid:#383835;
  --s1:{SERIES_DARK[0]}; --s2:{SERIES_DARK[1]}; --s3:{SERIES_DARK[2]}; --s4:{SERIES_DARK[3]}; }}
body {{ margin:0; background:var(--surface); color:var(--ink); font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
main {{ max-width:980px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:16px; margin:32px 0 8px; }} .sub {{ color:var(--ink-2); font-size:13px; }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin:18px 0; }}
.tile {{ background:var(--surface-2); border-radius:10px; padding:14px 16px; }} .tile .k {{ font-size:13px; color:var(--ink-2); }} .tile .v {{ font-size:28px; font-weight:600; margin:4px 0 2px; }}
figure {{ margin:14px 0 0; }} figcaption {{ margin-bottom:6px; }} svg {{ width:100%; height:auto; display:block; }}
.legend {{ font-size:13px; color:var(--ink-2); margin-left:10px; }} .sw {{ display:inline-block; width:12px; height:12px; border-radius:3px; margin:0 4px 0 8px; vertical-align:-1px; }}
.s1 {{ fill:var(--s1); background:var(--s1); }} .s2 {{ fill:var(--s2); background:var(--s2); }} .s3 {{ fill:var(--s3); background:var(--s3); }} .s4 {{ fill:var(--s4); background:var(--s4); }}
.line {{ fill:none; stroke-width:2px; }} .line.s1 {{ stroke:var(--s1); }} .line.s2 {{ stroke:var(--s2); }}
.ring {{ stroke:var(--surface); stroke-width:2px; }} .grid {{ stroke:var(--grid); stroke-width:1px; }}
.tick, .lbl, .val {{ font-size:12px; fill:var(--ink-2); }} .lbl {{ fill:var(--ink); }} .val.on {{ fill:#fff; font-size:11px; }}
.bar:hover rect, .seg:hover {{ opacity:.85; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; margin-top:6px; }} th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--grid); }} th {{ color:var(--ink-2); font-weight:500; }}
details {{ margin-top:6px; font-size:13px; color:var(--ink-2); }}
.sample {{ background:var(--surface-2); border-radius:10px; padding:12px 14px; margin:10px 0; }} .sample .k {{ font-weight:600; }} .sample p {{ margin:6px 0; }}
.ok {{ color:var(--good); font-weight:600; }} .bad {{ color:var(--critical); font-weight:600; }}
"""


def render_dashboard(s: dict) -> str:
    live = s["policies"][0]
    baseline = s["fraud_at_risk"]
    tiles = [
        ("Fraud stopped before shipping", f"{live['fraud stopped %']:.1f}%", f"{live['fraud stopped']} bookings"),
        ("Legitimate bookings blocked", f"{live['legit blocked %']:.2f}%", f"{live['legit blocked']} of {s['n_legit']}"),
        ("Loss avoided vs no detection", f"{100 * (1 - live['realised cost ₹'] / baseline):.0f}%", f"{_fmt_inr(baseline)} at risk → {_fmt_inr(live['realised cost ₹'])} realised cost"),
        ("Scoring latency p99", f"{s['latency_ms']['p99']:.1f} ms", "features + rules + model + conformal + decision + ledger"),
    ]
    tile_html = "".join(f'<div class="tile"><div class="k">{html.escape(k)}</div><div class="v">{html.escape(v)}</div><div class="sub">{html.escape(sub)}</div></div>' for k, v, sub in tiles)

    pol_rows = [(p["policy"], p["realised cost ₹"], f"{p['policy']}: fraud stopped {p['fraud stopped']} · legit blocked {p['legit blocked']} · verifications {p['legit asked to verify']} · reviews {p['reviews']}") for p in s["policies"]]
    pol_rows.append(("no detection (ship everything)", baseline, "all fraud ships"))
    scen_rows = [(r["scenario"], 100 * r["recall"], f"{r['scenario']}: {r['stopped']}/{r['n']} stopped") for r in s["scenario_recall"]]

    top = "".join(f"<tr><td>{r['booking_id']}</td><td>{r['p']:.3f}</td><td>{r['action']}</td><td>{'fraud · ' + r['scenario'] if r['fraud'] else 'legit'}</td></tr>" for r in s["top_p"])
    samples = "".join(f"<div class='sample'><div class='k'>{html.escape(x['label'])} — {x['booking_id']}</div><p><b>Analyst:</b> {html.escape(x['narrative'])}</p>" +
                      (f"<p><b>Customer:</b> {html.escape(x['customer'])}</p>" if x['customer'] else "") +
                      f"<p class='sub'>grounding verifier: {'PASS' if x['grounded'] else 'FAIL'}</p></div>" for x in s["samples"])
    led = s["ledger"]
    pol_tbl = "".join(f"<tr><td>{p['policy']}</td><td>{p['realised cost ₹']:,}</td><td>{p['fraud stopped']}</td><td>{p['legit blocked']}</td><td>{p['legit asked to verify']}</td><td>{p['reviews']}</td><td>{p['ALLOW/STEP_UP/HOLD/BLOCK']}</td></tr>" for p in s["policies"])
    sens = "".join(f"<tr><td>{r['charge']}</td><td>{r['p']}</td><td>{r['individual']}</td><td>{r['sme']}</td><td>{r['ecommerce']}</td></tr>" for r in s["sensitivity"])

    css = base_css()
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FraudShield Replay</title><style>{css}</style></head><body><main>
<h1>FraudShield — booking-time fraud screening, live replay</h1>
<div class="sub">{s['n_stream']:,} bookings replayed ({s['n_fraud']} fraudulent) · model {html.escape(s['training']['model_version'])} · synthetic stream, relative numbers only</div>
<div class="tiles">{tile_html}</div>
{_line_chart(s['daily'])}
<h2>Decision policy comparison</h2>
<div class="sub">Same calibrated probabilities for every booking; realised cost = fraud that shipped + lost revenue and churn from blocking legitimate customers + verification friction + analyst time.</div>
{_hbar(pol_rows, "Realised cost over the replay (lower is better)", _fmt_inr)}
<table><thead><tr><th>policy</th><th>realised cost ₹</th><th>fraud stopped</th><th>legit blocked</th><th>legit verifications</th><th>reviews</th><th>ALLOW / STEP_UP / HOLD / BLOCK</th></tr></thead><tbody>{pol_tbl}</tbody></table>
<h2>Same probability, different customer, different action</h2>
<div class="sub">Expected-cost minimisation picks the cheapest action given the loss at stake and the customer's value.</div>
<table><thead><tr><th>charge</th><th>fraud probability</th><th>individual (LTV ₹2k)</th><th>SME (LTV ₹60k)</th><th>e-commerce (LTV ₹3 lakh)</th></tr></thead><tbody>{sens}</tbody></table>
{_stacked(s['actions_by_cohort'])}
{_hbar(scen_rows, "Fraud stopped before shipping, by attack scenario (%)", lambda v: f"{v:.0f}%", cls="s3")}
<h2>Highest-risk bookings in the replay</h2>
<table><thead><tr><th>booking</th><th>p(fraud)</th><th>action</th><th>truth</th></tr></thead><tbody>{top}</tbody></table>
<h2>Explanations (generated off the decision path)</h2>{samples}
<h2>Audit ledger</h2>
<p>Hash chain over {led['records']} decision records: <span class="{'ok' if led['valid'] else 'bad'}">{'valid' if led['valid'] else 'BROKEN'}</span> ·
tampering with one field of one record is detected: <span class="{'ok' if led['tamper_detected'] else 'bad'}">{'yes' if led['tamper_detected'] else 'no'}</span> ·
deterministic replay of a stored decision reproduces its probability: <span class="{'ok' if led['replay'].get('reproduced') else 'bad'}">{'yes' if led['replay'].get('reproduced') else 'no'}</span></p>
<p class="sub">Latency p50 {s['latency_ms']['p50']:.2f} ms · p95 {s['latency_ms']['p95']:.2f} ms · p99 {s['latency_ms']['p99']:.2f} ms (single process, in-memory feature store).</p>
</main></body></html>"""


if __name__ == "__main__":
    import sys
    from pathlib import Path
    stats = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Path(sys.argv[2]).write_text(render_dashboard(stats), encoding="utf-8")
