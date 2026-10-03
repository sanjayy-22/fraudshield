#!/usr/bin/env bash
# Scripted demo of api_dataco.py. Start the service first:
#   cd prototypes/fraudshield-pipeline && uvicorn api_dataco:app --port 8081
# then: bash demo_requests.sh [base_url]
set -euo pipefail
BASE="${1:-http://127.0.0.1:8081}"
show() { python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps(d, indent=1)[:2500])'; }

# a real customer (12366, six earlier orders) placing a new two-line order
order() {  # $1 = order_id, $2 = payment_type, $3 = optional extra JSON field
  cat <<JSON
{"order_id": $1, "ts": "2018-02-15 10:30", "customer_id": 12366, "payment_type": "$2",
 "shipping_mode": "First Class", "days_shipment_scheduled": 1, "market": "LATAM",
 "order_region": "Central America", "order_country": "El Salvador", "order_city": "San Salvador",
 "customer_segment": "Consumer", "customer_country": "EE. UU.", "customer_city": "Saint Paul"$3,
 "items": [
  {"quantity": 1, "unit_price": 299.98, "discount": 15.0, "discount_rate": 0.05, "profit": 80.0, "profit_ratio": 0.28,
   "category": "Camping & Hiking", "department": "Fan Shop", "product_id": 957},
  {"quantity": 3, "unit_price": 50.0, "discount": 15.0, "discount_rate": 0.10, "profit": 30.0, "profit_ratio": 0.22,
   "category": "Cleats", "department": "Apparel", "product_id": 365}]}
JSON
}

echo "== 1. health"; curl -s "$BASE/health" | show
echo; echo "== 2. new order paid by TRANSFER  → expect STEP_UP or HOLD"
order 900001 TRANSFER "" | curl -s -X POST "$BASE/dataco/score" -H 'content-type: application/json' -d @- | show
echo; echo "== 3. the same order paid by DEBIT → expect ALLOW"
order 900002 DEBIT "" | curl -s -X POST "$BASE/dataco/score" -H 'content-type: application/json' -d @- | show
echo; echo "== 4. the same order with a post-booking field → expect 422 'leak fields not allowed'"
order 900003 TRANSFER ', "delivery_status": "Shipping canceled"' | \
  curl -s -w '\nHTTP %{http_code}\n' -X POST "$BASE/dataco/score" -H 'content-type: application/json' -d @-
echo; echo "== 5. a real test-window order that was flagged SUSPECTED_FRAUD"
curl -s "$BASE/dataco/orders/62506" | show
echo; echo "== 6. ledger"; curl -s "$BASE/dataco/ledger/verify" | show
