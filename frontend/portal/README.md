# FraudShield UI demo

Standalone React + TypeScript frontend for the supplied customer portal and fraud investigation console specification. The existing `frontend/index.html`, Python services, trained models, and original demo remain unchanged.

## Run

```sh
cd frontend/portal
npm install
npm run dev
```

Open **http://127.0.0.1:5174**. Port 5174 avoids the original demo on 5173.

```sh
npm run build
npm run preview
npm test
```

## Demo accounts

- Customer: `aarav@example.com` / `demo123`
- Admin: `admin@example.com` / `demo123`
- Registration creates another local demo customer. Use fictitious information only.

Authentication is a browser-only demonstration: the role-specific route guards are navigation controls, not a security boundary. Passwords are not stored or verified against a real identity service; an existing demo account accepts any password of at least six characters. No JWT, backend authentication, or payment gateway is implemented.

## Working demo

1. Sign in as a customer. Explore the dashboard, shipment list, inbox, alerts, and profile.
2. Create a shipment through the seven-step wizard. Its draft survives refreshes in the same browser tab. The summary recalculates weight/dimensions, collection, protection, discount, and price immediately.
3. Use a declared contents value of ₹50,000 or more for the admin showcase. The mock service intentionally supplies a multi-signal scenario for this demonstration; high value alone is not real evidence of fraud.
4. Apply `WELCOME10` for a mock shipping discount, then confirm the simulated payment. A tracking ID and inbox update are created.
5. Switch workspace and sign in at `/admin/login`. The new shipment appears in the package queue.
6. Open its investigation: package details, risk score, simulated SHAP chart, account history, masked connections, and decision history.
7. Approve, hold, or block with a reason and confirmation. The status changes in filtered queues, a customer update is added, and an audit entry is retained with the original risk evidence.

There are 24 seeded customers and 64 shipments. New data and decisions are stored in localStorage (`fraudshield-portal-v1`). Sessions and per-customer drafts use sessionStorage. Browser storage is not a secure production database or a tamper-evident ledger. No network request is made to the existing fraud backend.

## Structure

- `src/services/api/`: auth, shipment, tracking, admin, risk, and user service contracts; mock data, persistence, quote calculations, and deterministic scoring.
- `src/contexts/`: authentication and shipment draft state.
- `src/components/layout/`: sidebar and navigation.
- `src/components/shipment/`: reusable wizard forms, live summary, stepper, tables, and timeline.
- `src/components/admin/`: investigation chart, risk factors, user history, connections, package table, and decision modal.
- `src/pages/`: customer and admin route views.

Replace service implementations with authenticated FastAPI requests to integrate later. Keep the same typed return contracts and enforce authorization on the server. Only frontend demonstration work is included here.

## Risk display

The centralized mock formula is `round(0.4 × (ruleScore / 40 × 100) + 0.6 × aiScore)`.
Levels are LOW 0–29, MEDIUM 30–59, HIGH 60–79, CRITICAL 80–100. The showcase uses 40/40 rules and 85% simulated AI for a consistent overall score of 91. Model and SHAP values are explicitly illustrative, not predictions from the trained model.

## Verification

Service integration tests cover quote changes, risk boundaries, creation → tracking → admin visibility, account-scoped tracking, demo roles, decision validation, evidence retention, audit history, and persistence. Browser visual and interaction verification requires access to the local preview.

All public routes and the requested customer/admin routes are implemented, with an additional `/admin/audit` view. Client-side routing requires an index.html fallback if this static build is hosted later.
