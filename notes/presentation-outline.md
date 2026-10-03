# Presentation outline: FraudShield on real data

Slide deck (claude.ai, private until shared; downloads as .pptx or PDF):
https://claude.ai/artifact/3ynrA5eCDMR5CyU91qUU7k
Interactive dashboard: `visuals/dashboard_dataco.html` (also published privately at
https://claude.ai/artifact/DjsFnKxmAdUpFaGsYmmw5w).

Every number below comes from `notes/comparison-dataco.md`, `prototypes/fraudshield-pipeline/results_dataco.md`
or the README's synthetic headline results.

| # | Slide | Message | Speaker notes |
|---|---|---|---|
| 1 | FraudShield on real data | What 13,670 real DataCo orders say about booking-time fraud detection | Simulated data: it works. DataCo: the 0.99 is a leak, the honest number is near chance inside TRANSFER, and the decision layer still pays off. |
| 2 | Decide at booking time, explain it, audit it | ALLOW / STEP_UP / HOLD / BLOCK, in milliseconds, explained, replayable | The model gives a probability; the decision layer turns it into an action. |
| 3 | One path from order to audited decision | Features → rules → calibrated model → conformal set → decision → ledger | Same code on DataCo; only the feature step is new, and it bans post-booking columns. |
| 4 | On a simulated stream with fraud rings, it works | AUC 0.998 · 94.7% fraud stopped · 0.30% legit blocked · p99 3.4 ms | Synthetic, relative numbers only. |
| 5 | Then we ran it on real orders | 65,752 orders, 1,488 fraud (2.26%), all TRANSFER; split by date | Test window: 13,670 orders, 308 fraud. |
| 6 | The 0.99 trap | ROC-AUC 0.990 with post-booking columns; every fraud is 'Shipping canceled' | delivery_status carries 92% of split gain. Not deployable. |
| 7 | With booking-time features only, fraud looks random | 0.880 all orders, 0.539 inside TRANSFER (CI 0.507–0.572) | Payment type gives ~0.87 for free; adding entity features drops TRANSFER AUC to 0.508. |
| 8 | Nothing beyond payment type separates fraud | Entity ratios 0.97–1.03; repeat customers 7.5% vs 8.3%; anomaly 0.51; shuffle null 0.501 ± 0.013 | Inference: label close to random within TRANSFER; not documented by the dataset. |
| 9 | What still works: choosing the action | Cost-sensitive policy $94.7k vs $200.0k allow-all; thresholds cost more than nothing | Simulated costs and stated assumptions; decision-layer win, not detection win. |
| 10 | Live demo | TRANSFER → HOLD, DEBIT → ALLOW, leak field → 422; ledger verified | `uvicorn api_dataco:app --port 8081`, then `bash demo_requests.sh`. |
| 11 | Next steps | Tell it straight; prove detection on PaySim / IEEE-CIS; stress the decision layer | |

## Running the live demo
```bash
cd prototypes/fraudshield-pipeline
python3 demo_dataco.py                      # replay, results_dataco.md, stats_dataco.json, visuals/dashboard_dataco.html
uvicorn api_dataco:app --port 8081          # fits on 2015 → 2017-H1 at start-up (~15 s)
bash demo_requests.sh                       # in a second terminal
```
