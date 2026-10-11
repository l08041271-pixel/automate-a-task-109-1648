# API cookbook (copy and paste)

Set these once per shell session:

```bash
export BASE=http://127.0.0.1:8000
export KEY="$(grep '^ADMIN_API_KEY' .env | cut -d'"' -f2)"
```

---

## Health

```bash
curl -s $BASE/health | python -m json.tool
curl -s $BASE/health/live
```

## Log in and keep the token

```bash
TOKEN=$(curl -s -X POST $BASE/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"owner@massagevip.sa","password":"YOUR_PASSWORD"}' \
  | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

export AUTH="Authorization: Bearer $TOKEN"
curl -s $BASE/api/auth/me -H "$AUTH"
```

## Capture a lead (the public form endpoint)

```bash
curl -s -X POST $BASE/api/leads \
  -H 'Content-Type: application/json' \
  -d '{
        "source": "WEBSITE_FORM",
        "name": "Layla",
        "phone": "0555111222",
        "service_interest": "home massage",
        "initial_inquiry": "I want to book an appointment tonight",
        "preferred_time_text": "tonight",
        "location_text": "Riyadh",
        "consent_status": "GRANTED",
        "consent_source": "website_form_checkbox",
        "utm_source": "instagram",
        "utm_medium": "social",
        "utm_campaign": "riyadh-launch"
      }' | python -m json.tool
```

Expect `201`. Posting the identical body again returns `200` with the same
`id` — that is the duplicate guard working, not an error.

## Read leads

```bash
# All leads
curl -s "$BASE/api/leads?limit=20" -H "$AUTH" | python -m json.tool

# Only HOT leads
curl -s "$BASE/api/leads?classification=HOT" -H "$AUTH" | python -m json.tool

# One lead
LEAD_ID=<paste-id>
curl -s "$BASE/api/leads/$LEAD_ID" -H "$AUTH" | python -m json.tool
```

## Re-score and read the explanation

```bash
curl -s -X POST "$BASE/api/leads/$LEAD_ID/score" -H "$AUTH" | python -m json.tool
```

## Update a lead / move the pipeline

```bash
curl -s -X PATCH "$BASE/api/leads/$LEAD_ID" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"stage":"CONTACTED","preferred_time_at":"2030-01-01T18:00:00+03:00"}' \
  | python -m json.tool
```

### About pipeline transitions

Allowed moves are `NEW → CONTACTED → QUALIFIED → BOOKED → COMPLETED`
(plus `LOST` and the documented back-steps).

* A **STAFF** token that attempts an illegal jump (for example `NEW` → `BOOKED`)
  gets **409** with an explanation.
* An **OWNER** token is allowed to override the guard, so the same call returns
  **200**. This is deliberate — the owner is the person who fixes a messy
  pipeline — but it means you should not use an owner token to test the guard.

To see the 409 for yourself, create a staff user and use that token:

```bash
curl -s -X POST $BASE/api/auth/users   -H "$AUTH" -H 'Content-Type: application/json'   -d '{"email":"staff@massagevip.sa","password":"a-long-enough-password","role":"STAFF"}'

STAFF_TOKEN=$(curl -s -X POST $BASE/api/auth/login   -H 'Content-Type: application/json'   -d '{"email":"staff@massagevip.sa","password":"a-long-enough-password"}'   | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -s -o /dev/null -w '%{http_code}\n' -X PATCH "$BASE/api/leads/$LEAD_ID"   -H "Authorization: Bearer $STAFF_TOKEN" -H 'Content-Type: application/json'   -d '{"stage":"BOOKED"}'
# 409
```

## Bookings

```bash
# Record a request (never a confirmation)
curl -s -X POST $BASE/api/bookings \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"lead_id":"'$LEAD_ID'","requested_time_at":"2030-01-01T18:00:00+03:00","price_amount":300}'

# This FAILS with 409 - confirmation requires verification
curl -s -X PATCH "$BASE/api/bookings/<booking-id>" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"status":"CONFIRMED"}'

# This succeeds: a human verified availability
curl -s -X PATCH "$BASE/api/bookings/<booking-id>" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"status":"CONFIRMED","verified":true,"verified_by":"owner@massagevip.sa",
       "verification_notes":"Called the customer; checked the roster."}'
```

## Follow-ups

```bash
curl -s "$BASE/api/follow-ups" -H "$AUTH" | python -m json.tool
curl -s -X POST "$BASE/api/follow-ups/run" -H "$AUTH" | python -m json.tool
```

Response note: *"Drafts only — no message is sent to a customer by this run."*

## Analytics and the growth agent

```bash
curl -s "$BASE/api/analytics/summary?days=30" -H "$AUTH" | python -m json.tool
curl -s -X POST "$BASE/api/growth/run?days=7" -H "$AUTH" | python -m json.tool
curl -s "$BASE/api/growth/marketing-drafts?campaign_name=Riyadh%20Launch" -H "$AUTH"
```

## Simulate a WhatsApp webhook locally

```bash
export WA_SECRET="$(grep '^WHATSAPP_APP_SECRET' .env | cut -d'"' -f2)"

python - <<'PY'
import hashlib, hmac, json, os, time, urllib.request
secret = os.environ["WA_SECRET"].encode()
payload = {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{
    "field": "messages", "value": {
        "metadata": {"phone_number_id": "PN"},
        "contacts": [{"profile": {"name": "Sara"}, "wa_id": "966500000777"}],
        "messages": [{"from": "966500000777", "id": "wamid.TEST1",
                      "timestamp": str(int(time.time())), "type": "text",
                      "text": {"body": "I want to book a home massage in Riyadh tonight"}}]}}]}]}
body = json.dumps(payload).encode()
sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/webhooks/whatsapp", data=body,
    headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig})
print(urllib.request.urlopen(req).read().decode())
PY
```

Then check the result: a contact, a conversation, a scored lead (HOT), an
escalation to the owner, and a **drafted** reply that was not sent.

## Admin API key instead of a JWT

```bash
curl -s $BASE/api/analytics/summary -H "X-API-Key: $KEY" | python -m json.tool
```
