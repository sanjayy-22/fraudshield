"""Static HTML dashboard for the DataCo real-data replay (no external dependencies).

Renders from stats_dataco.json (written by demo_dataco.py): headline tiles, the leak-vs-honest
AUC comparison with the shuffled-label null, monthly fraud rate, policy costs, live action mix
by payment type, the highest-scored orders with their reasons, and the audit-ledger status.
Shares CSS, color roles, dark mode and chart helpers with dashboard.py.
"""
from __future__ import annotations

import html
import json

from dashboard import ACTIONS, _hbar, _stacked, base_css


def _usd(v: float) -> str:
    return f"${v:,.0f}"


BINARY = {"is_transfer", "cust_new_country", "cust_new_city"}


def _reason(x: dict) -> str:
    """'paid by bank transfer' rather than 'paid by bank transfer = 1'; readable numbers."""
    v = x["value"]
    if x["feature"] in BINARY:
        return x["label"] if v == 1 else f"not {x['label']}"
    if isinstance(v, str):
        return f"{x['label']}: {v}"
    if abs(v) >= 100:
        return f"{x['label']}: {v:,.0f}"
    return f"{x['label']}: {int(v) if float(v).is_integer() else format(v, '.2g')}"


def _auc_dots(models: list[dict], null: dict | None, w=900) -> str:
    """TRANSFER-scope ROC-AUC per model: dot + 95% CI whisker, chance line, shuffled-label null band."""
    if not models:
        return ""
    lw, mr, row = 260, 70, 34
    h = len(models) * row + 40
    x0, x1 = 0.44, 1.0

    def x(v):
        return lw + (w - lw - mr) * (v - x0) / (x1 - x0)

    out = ""
    for t in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        out += (f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="6" y2="{h - 26}"/>'
                f'<text class="tick" x="{x(t):.1f}" y="{h - 8}" text-anchor="middle">{t:.1f}</text>')
    if null:
        out += (f'<rect x="{x(null["lo"]):.1f}" y="6" width="{x(null["hi"]) - x(null["lo"]):.1f}" height="{h - 32}" '
                f'class="nullband"><title>shuffled-label null (E5): {null["lo"]:.3f}–{null["hi"]:.3f}, '
                f'mean {null["mean"]:.3f}</title></rect>')
    out += f'<line class="chance" x1="{x(0.5):.1f}" x2="{x(0.5):.1f}" y1="6" y2="{h - 26}"/>'
    for i, m in enumerate(models):
        yy = 22 + i * row
        cls = "s2" if m["leaky"] else "s1"
        lo, hi = m["transfer_ci"]
        out += (f'<g class="bar"><title>{html.escape(m["label"])}: ROC-AUC inside TRANSFER {m["transfer_auc"]:.3f} '
                f'(95% CI {lo:.3f}–{hi:.3f}); all orders {m["all_auc"]:.3f}</title>'
                f'<rect x="0" y="{yy - row / 2}" width="{w}" height="{row}" fill="transparent"/>'
                f'<text class="lbl" x="{lw - 12}" y="{yy + 4}" text-anchor="end">{html.escape(m["label"])}</text>'
                f'<line class="whisk {cls}" x1="{x(max(lo, x0)):.1f}" x2="{x(hi):.1f}" y1="{yy}" y2="{yy}"/>'
                f'<circle class="{cls} ring" cx="{x(m["transfer_auc"]):.1f}" cy="{yy}" r="6"/>'
                f'<text class="val" x="{x(hi) + 10:.1f}" y="{yy + 4}">{m["transfer_auc"]:.3f}</text></g>')
    legend = ('<i class="sw s1"></i>booking-time features <i class="sw s2"></i>post-booking columns (leak) '
              '<i class="sw nullsw"></i>shuffled-label null')
    rows = "".join(f"<tr><td>{html.escape(m['label'])}</td><td>{m['all_auc']:.3f}</td><td>{m['transfer_auc']:.3f}</td>"
                   f"<td>{m['transfer_ci'][0]:.3f}–{m['transfer_ci'][1]:.3f}</td></tr>" for m in models)
    return (f'<figure><figcaption><strong>ROC-AUC inside TRANSFER orders, test window (95% CI)</strong>'
            f'<span class="legend">{legend}</span></figcaption>'
            f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="AUC inside TRANSFER orders by model">{out}</svg>'
            f'<details><summary>table view</summary><table><thead><tr><th>model</th><th>ROC-AUC all orders</th>'
            f'<th>ROC-AUC TRANSFER</th><th>95% CI</th></tr></thead><tbody>{rows}</tbody></table></details></figure>')


def _rate_lines(monthly: list[dict], w=900, h=250) -> str:
    """Monthly fraud rate: TRANSFER orders vs all orders (two lines, legend, hover per month, table)."""
    ml, mr, mt, mb = 44, 34, 14, 30
    n = len(monthly)
    ymax = 14.0
    xs = [ml + i * (w - ml - mr) / max(n - 1, 1) for i in range(n)]

    def y(v):
        return mt + (h - mt - mb) * (1 - v / ymax)

    def path(key):
        return "M" + " L".join(f"{xs[i]:.1f},{y(100 * m[key]):.1f}" for i, m in enumerate(monthly))

    grid = "".join(f'<line class="grid" x1="{ml}" x2="{w - mr}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="tick" x="{ml - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{t}%</text>' for t in (0, 4, 8, 12))
    ticks = "".join(f'<text class="tick" x="{xs[i]:.1f}" y="{h - 10}" text-anchor="middle">{monthly[i]["month"]}</text>'
                    for i in range(0, n, 6))
    pts = "".join(f'<g class="pt"><rect x="{xs[i] - 6:.1f}" y="{mt}" width="12" height="{h - mt - mb}" fill="transparent">'
                  f'<title>{m["month"]}: TRANSFER {100 * m["transfer_rate"]:.1f}% · all orders {100 * m["all_rate"]:.1f}%</title></rect>'
                  f'<circle class="s2 ring" cx="{xs[i]:.1f}" cy="{y(100 * m["transfer_rate"]):.1f}" r="3"/>'
                  f'<circle class="s1 ring" cx="{xs[i]:.1f}" cy="{y(100 * m["all_rate"]):.1f}" r="3"/></g>'
                  for i, m in enumerate(monthly))
    rows = "".join(f"<tr><td>{m['month']}</td><td>{100 * m['transfer_rate']:.2f}%</td><td>{100 * m['all_rate']:.2f}%</td></tr>"
                   for m in monthly)
    return (f'<figure><figcaption><strong>Fraud rate by month</strong><span class="legend"><i class="sw s2"></i>TRANSFER orders '
            f'<i class="sw s1"></i>all orders</span></figcaption>'
            f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="monthly fraud rate">{grid}{ticks}'
            f'<path d="{path("transfer_rate")}" class="line s2"/><path d="{path("all_rate")}" class="line s1"/>{pts}</svg>'
            f'<details><summary>table view</summary><table><thead><tr><th>month</th><th>TRANSFER</th><th>all orders</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></details></figure>')


def render_dashboard_dataco(s: dict) -> str:
    exp = {m["label"]: m for m in s["experiments"]["models"]}
    leaky = exp.get("leaky model (post-booking columns)")
    honest = exp.get("honest GBM", dict(all_auc=s["live_model"]["all_auc"], transfer_auc=s["live_model"]["transfer_auc"],
                                         transfer_ci=s["live_model"]["transfer_ci"]))
    live = s["policies"]["cost-sensitive + conformal (live)"]
    base = s["fraud_at_risk_usd"]
    nul = s["experiments"]["null"]
    tiles = [
        ("Leaky model ROC-AUC", f"{leaky['all_auc']:.3f}" if leaky else "n/a",
         "with post-booking columns, as most DataCo notebooks report: not deployable"),
        ("Honest model ROC-AUC", f"{honest['all_auc']:.3f}", "booking-time features only; nearly all of it is payment type"),
        ("…inside TRANSFER orders", f"{honest['transfer_auc']:.3f}",
         f"95% CI {honest['transfer_ci'][0]:.3f}–{honest['transfer_ci'][1]:.3f}"
         + (f"; shuffled labels give {nul['mean']:.3f} ± {nul['sd']:.3f}" if nul else "")),
        ("Fraud stopped (live policy)", f"{live['fraud_stopped']}/{s['n_fraud']}",
         f"{_usd(live['cost_usd'])} realised cost vs {_usd(base)} if everything ships*"),
    ]
    tile_html = "".join(f'<div class="tile"><div class="k">{html.escape(k)}</div><div class="v">{html.escape(v)}</div>'
                        f'<div class="sub">{html.escape(sub)}</div></div>' for k, v, sub in tiles)

    pol_rows = [(p, d["cost_usd"], f"{p}: fraud stopped {d['fraud_stopped']}/{s['n_fraud']} · legit blocked {d['legit_blocked']} · "
                 f"verifications {d['legit_verified']} · reviews {d['reviews']}") for p, d in s["policies"].items()]
    pol_tbl = "".join(f"<tr><td>{html.escape(p)}</td><td>{_usd(d['cost_usd'])}</td><td>{d['fraud_stopped']}/{s['n_fraud']}</td>"
                      f"<td>{d['legit_blocked']}</td><td>{d['legit_verified']}</td><td>{d['reviews']}</td>"
                      f"<td>{' / '.join(str(d['actions'].get(a, 0)) for a in ACTIONS)}</td></tr>" for p, d in s["policies"].items())
    top = "".join(
        f"<tr><td>{r['order_id']}</td><td>{r['p']:.3f}</td><td>{r['action']}</td><td>{r['payment']}</td>"
        f"<td>{_usd(r['value'])}</td><td>{'<b>fraud</b>' if r['fraud'] else 'legit'}</td>"
        f"<td>{html.escape('; '.join(_reason(x) for x in r['reasons']))}</td></tr>"
        for r in s["top_orders"])
    led = s["ledger"]
    w = s["window"]

    def flag(ok, yes="yes", no="no"):
        return f'<span class="{"ok" if ok else "bad"}">{yes if ok else no}</span>'

    extra_css = """
.nullband { fill:var(--grid); opacity:.9; } .nullsw { background:var(--grid); }
.chance { stroke:var(--ink-3); stroke-width:1px; stroke-dasharray:3 3; }
.whisk { stroke-width:2px; stroke-linecap:round; } .whisk.s1 { stroke:var(--s1); } .whisk.s2 { stroke:var(--s2); }
.note { background:var(--surface-2); border-radius:10px; padding:12px 14px; margin:14px 0; font-size:13px; color:var(--ink-2); }
.tablewrap { overflow-x:auto; }
@media (max-width: 680px) {
  figure { overflow-x:auto; } figure svg { min-width:640px; }
  .tablewrap table { min-width:760px; }
}
"""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FraudShield DataCo Replay</title><style>{base_css()}{extra_css}</style></head><body><main>
<h1>FraudShield on real data: DataCo Supply Chain</h1>
<div class="sub">Test window {w['start']} → {w['end']}: {w['orders']:,} orders, {w['fraud']} flagged SUSPECTED_FRAUD, all of them paid by TRANSFER
({w['transfer_orders']:,} TRANSFER orders) · trained on 2015–2016, calibrated on 2017-H1 · model {html.escape(s['training']['model_version'])}</div>
<div class="tiles">{tile_html}</div>

<h2>The 0.99 is a leak</h2>
<div class="sub">Every model scored on the same test orders. Inside TRANSFER orders, where all the fraud is, only the model that sees
post-booking columns (delivery_status = 'Shipping canceled') separates fraud. Booking-time models sit at or just above the shuffled-label null.</div>
{_auc_dots(s['experiments']['models'], nul)}

{_rate_lines(s['monthly'])}

<h2>What the decision layer still buys</h2>
<div class="sub">Same calibrated probabilities for every order. The cost-sensitive policy uses the TRANSFER risk (≈8%) together with
each order's value and the customer's value to choose verify / review / allow. That is a gain from choosing actions, not from ranking orders better.
Threshold policies fall inside TRANSFER, where ranking is near random, and end up costing more than doing nothing.</div>
{_hbar(pol_rows, "Realised cost over the replay, USD (lower is better)*", _usd)}
<div class="tablewrap"><table><thead><tr><th>policy</th><th>cost</th><th>fraud stopped</th><th>legit blocked</th><th>legit verified</th><th>reviews</th><th>ALLOW / STEP_UP / HOLD / BLOCK</th></tr></thead><tbody>{pol_tbl}</tbody></table></div>
{_stacked(s['live_actions_by_payment'], title="Live decisions by payment type")}

<h2>Highest-scored orders</h2>
<div class="sub">Reasons are the top TreeSHAP contributions. Inside TRANSFER they are small next to the payment-type term, so they describe noise more than fraud.</div>
<div class="tablewrap"><table><thead><tr><th>order</th><th>p(fraud)</th><th>action</th><th>payment</th><th>value</th><th>truth</th><th>top reasons</th></tr></thead><tbody>{top}</tbody></table></div>

<h2>Audit ledger</h2>
<p>Hash chain over {led['records']:,} decision records: {flag(led['verified'], 'valid', 'BROKEN')} ·
tampering with one record is detected: {flag(led['tamper_detected'])} ·
replaying <code>{html.escape(led['replay_id'])}</code> from its stored features reproduces the probability: {flag(led['replay_reproduced'])}</p>

<div class="note">* Costs are a simulation, not DataCo facts. Money = order value in USD. LTV = max(2 × the customer's prior spend, order value).
Analyst review = $5. Step-up pass rates and the analyst catch rate come from <code>CostParams</code>. Ambiguous conformal sets (α = 0.10):
{s['ambiguous']:,} orders. Source: <code>prototypes/fraudshield-pipeline/demo_dataco.py</code>; details in <code>notes/comparison-dataco.md</code>.</div>
</main></body></html>"""


if __name__ == "__main__":
    import sys
    from pathlib import Path
    stats = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Path(sys.argv[2]).write_text(render_dashboard_dataco(stats), encoding="utf-8")
