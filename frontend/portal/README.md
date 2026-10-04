# FraudShield shipping and approval portal

React + TypeScript portal with a connection to the saved LightGBM model. Razorpay Checkout and Amazon SES can be connected for payment and verification email. PostgreSQL stores each account's last verified device type and pending device-login codes. Booking, account, and review records are still stored in this browser; carrier dispatch is simulated. The original frontend and api_dataco booking desk are separate and unchanged.

## Run

### Start the frontend, backend, and PostgreSQL with Docker

Install Docker Desktop (including Docker Compose), copy the repository-root `.env.example` to `.env`, and set a long random alphanumeric `POSTGRES_PASSWORD`. Add Razorpay and Amazon SES credentials to `.env` to enable checkout and verification email; containers can start without those provider credentials, but payments and email verification will remain unavailable. From the repository root, run:

```powershell
docker compose up --build
```

Open http://localhost:5174. Compose waits for PostgreSQL before starting the backend and for the backend before starting the frontend. Stop with `Ctrl+C`; run `docker compose down` to stop the stack. The database volume remains so device verification survives restarts. `docker compose down -v` deletes the database volume and its contents.

Start the model adapter in one terminal, from the repository root:

```powershell
cd prototypes/fraudshield-pipeline
python -m uvicorn api_portal:app --host 127.0.0.1 --port 8082
```

Start the portal in another terminal, from the repository root:

```powershell
cd frontend/portal
npm install
npm run dev
```

Open http://127.0.0.1:5174. Vite proxies /portal-api to the adapter on port 8082. Its preview command uses the same proxy. Restart an older Vite process after updating its configuration. No model training or original-backend reset is needed.

Dependencies for the adapter: Python with fastapi, uvicorn, pydantic 2, numpy, pandas, scikit-learn, lightgbm, joblib, and the dependencies of the existing fraudshield package. The saved artifact is models/dataco/fraudshield_dataco.pkl. Model-load compatibility warnings are retained in the admin's model limitations; inference passing is not proof of cross-version equivalence.

## Demonstrate the flow

1. Create a user account, then complete the seven-step shipment form and pay through Razorpay Checkout.
2. After payment is verified, the saved model and risk rules route the booking: score under 30 is **Approved** automatically; 30–59 requires an email code; 60 or higher, or an unavailable score, waits for admin review.
3. For email verification, enter the six-digit code sent to the customer. A correct code approves the booking automatically without admin action.
4. Keep the customer tracking page open. In another tab, sign in with an admin account at /admin/login. Sessions are per tab.
5. Open **Awaiting approval** at /admin/packages/pending. The new booking appears automatically for tabs on the same browser and origin.
6. Review sender/receiver contacts, package contents, value, collection details, payment receipt, actual ML score, rule signals, model limitations, and history. The **Why this shipment received this score** panel explains the score in titled points for every review status.
7. For bookings in admin review, approve, hold, or block with a reason. Approval means **Ready to ship**, with no pickup claimed.
8. An approved booking exposes a separate **Simulate dispatch** confirmation. It advances to Picked Up only after payment and approval. Hold, block, and unavailable scores prevent dispatch. Blocking does not issue a refund.
9. If model scoring fails, the paid booking remains in admin review with an **Unavailable** score. Approval remains disabled. Start/fix the model service and use **Retry model scoring**.

Duplicate confirmation references reuse the same receipt and booking. Decisions use a revision check so a second admin cannot silently overwrite a newer decision. Dispatch is idempotent. Pre-shipment decisions become read-only after dispatch. Each action keeps a snapshot of risk evidence; retrying scoring also retains the previous evidence.

The 24 seeded customers and 64 seeded shipments are sample data. Their scores and device/payment connections are clearly marked illustrative. New bookings use the saved model, with no simulated-score fallback.

## Device verification

The portal reduces browser information to one of three types (`desktop`, `mobile`, or `tablet`). If login comes from a type different from the account's `last_accessed_device_type`, the backend emails a one-time code and pauses sign-in. The user must verify that code before accessing the shipment form or paying. A successful verification updates `last_accessed_device_type` in PostgreSQL. New accounts trust the device used during account creation.

## Model mapping and limitations

The adapter uses the saved DataCo model and its fitted categorical encoder, calibration, and TreeSHAP contributions. It does not train the model, mutate its history, create bookings in api_dataco, or clear its ledger.

Portal inputs differ from DataCo order records:

- Contents value is a proxy for order value, converted from INR with the fixed demonstration factor 85 INR/USD. This is not a live exchange rate. Set FRAUDSHIELD_DEMO_INR_PER_USD in the Python service environment to configure it.
- Available inputs include quantity, category, country, booking time, and strictly earlier browser booking history.
- Missing profit, shipping-service, department, outcome, and DataCo payment fields remain NaN or unknown categories. UPI and netbanking do not imply DataCo TRANSFER.
- Unknown features remain labeled unknown in explanations, even when LightGBM assigns them a contribution.
- The mapping and probabilities are not validated for logistics fraud. The saved model's within-TRANSFER DataCo ROC-AUC was approximately 0.51. A low score does not verify identity or rule out fraud.

The displayed overall priority score is round(0.4 × normalized rules + 0.6 × ML score). Thresholds: LOW 0–29, MEDIUM 30–59, HIGH 60–79, CRITICAL 80–100. These thresholds prioritize reviews; none authorizes shipping automatically. The Suspicious tab selects unresolved bookings with an overall score of at least 60.

Rules for new bookings: account age under 30 days (+10); contents value at least ₹50,000 and greater than three times prior average, or no history (+15); four or more destination cities including this booking during seven days (+5). Device information is not collected, so new-device points are never invented. The existing 40-point normalization is preserved. SHAP shows top-six raw model log-odds contributions before probability calibration.

## Admin explainable AI

The package review page calls `POST /portal-api/explain`. Qwen rewrites the recorded rule conditions and the two strongest model contributions into short, titled points. Calculation, admin decision, payment caveats, and model limitations are rendered directly from the evidence. AI wording cannot change a score, threshold, decision, or shipping status. Unknown model inputs and seeded sample evidence remain explicitly labelled.

Configure the **repository-root** `.env` using `.env.example`. Keep `OPENROUTER_API_KEY` on the Python server only. The default `OPENROUTER_MODEL` is `qwen/qwen3.8-27b:free`; `FRAUDSHIELD_LLM=0` disables AI wording. Never use a `VITE_` variable for a provider secret. Restart the adapter after installing this feature.

### Payment and verification email configuration

Add credentials to the repository-root `.env` (never commit it): `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` for Checkout, plus `RAZORPAY_WEBHOOK_SECRET` if configuring payment webhooks. Start with Razorpay test-mode credentials. The backend creates the order, checks the Checkout signature, confirms the payment, and captures authorized payments. The public key ID is returned to Checkout; the secret stays server-side. Razorpay AVS is performed by Razorpay for eligible card payments only when enabled for your account and supported by the issuer/card/region. Enable it with Razorpay; the app cannot turn on an account-level payment feature. UPI and other non-card methods do not provide card AVS.

For Amazon SES, configure `SES_SMTP_HOST` for the SES region, `SES_SMTP_PORT` (587 by default), `SES_SMTP_USERNAME`, `SES_SMTP_PASSWORD`, and `SES_FROM_EMAIL`. Use SES SMTP credentials, verify the sender/domain, and request production sending access if your SES account is still in its sandbox. Set `FRAUDSHIELD_ADMIN_INVITE_CODE` to a random invite value to allow admin account creation. Do not put any of these values in chat, source files, or frontend environment variables.

The score cutoffs are a demonstration policy and can be adjusted in `frontend/portal/src/services/api/shipmentApi.ts`. A low score or successful email check removes the admin approval step, but this does not itself schedule a carrier pickup.

The editable system prompt is `prototypes/fraudshield-pipeline/fraudshield/portal_explain_system.txt`. The provider receives only bounded evidence cards: known rule names, numeric observations, and allowlisted model feature labels/directions. Sender/receiver details, payment credentials, booking identifiers, product descriptions, and free-text admin notes are excluded from the provider request. Input validation checks the score formula and rule consistency. Output checks cover evidence IDs, numeric facts, unknown/sample labels, model direction, and some unsupported assertions; they are not a guarantee against every possible misleading paraphrase. **View recorded evidence** lets the reviewer inspect each original fact.

Recorded evidence appears immediately while Qwen responds. Rate limits, missing credentials, invalid output, and provider failures use a clearly labelled evidence summary. Successful responses are cached for ten minutes; fallback responses for twenty seconds. A changed decision, revision, or evidence snapshot invalidates the cache. Refresh retries the provider, with a short server cooldown and bounded concurrent requests.

This endpoint accepts the browser's demonstration snapshot. It is loopback-only in the run instructions and has no production authentication. Before publishing, require authenticated admin requests, construct evidence from trusted server records, add per-user rate limits, and replace the demo data layer described below.

## Scope and persistence

localStorage key: fraudshield-portal-v1. Sessions, drafts, and confirmation references use sessionStorage. Existing saved reviews migrate to the new pending state and no longer show unapproved pickup progress. Web Locks serialize workflow writes across same-origin tabs; storage events refresh open views.

Authentication is a browser demonstration: any six-character password works for an existing demo account. Client role checks and browser data are not production security or trusted payment evidence. Payment signatures and one-time email codes are checked by the adapter, but workflow records and the final email-verification status are still browser data; the adapter's order/code state is in memory and is lost on restart. The model/payment/email adapter has no production authentication and is intended only for loopback use. Separate devices/browsers do not share the queue.

For production, replace the local service implementations with authenticated server endpoints, transactional storage, verified payment webhooks, trusted historical features, and carrier integration. Validate the model on representative shipping data before relying on its scores.

## Verification

```powershell
# frontend/portal
npm test
npm run build

# repository root
python -m pytest tests/test_portal_risk.py tests/test_portal_explain.py -q
```

Tests cover low/high-score routing, emailed step-up verification, duplicate confirmation, failed payment, unavailable/invalid model output, retry, roles, stale decisions, evidence snapshots, dispatch gating/idempotence, tracking scope, storage refresh/migration, actual saved inference, feature mapping, and API validation.

Explanation tests cover all review states, missing scores, evidence validation, privacy boundaries, provider failures, output checks, cache invalidation, frontend fallback, stale responses, and immediate rendering.

The implementation prompt is notes/implement-payment-admin-approval.md. Browser visual/interaction checks were not performed because browser access was denied.
