# Architecture and design decisions

This document records *why* the system is built the way it is. Each decision
names the constraint it serves, so a future maintainer can tell a deliberate
choice from an accident.

---

## 1. Constraints that shaped everything

| Constraint | Consequence |
|---|---|
| Minimise recurring cost | No Redis, no message broker, no separate worker. Rate limiting is in-process; scheduling uses GitHub Actions (free). |
| Must be usable from an Android phone | No build step for the dashboard (plain HTML/CSS/JS). Everything runs on SQLite locally. Copy-paste Termux commands. |
| Do not depend on a phone staying awake | The live service runs in the cloud; Termux is for development and testing only. |
| Never fabricate results | Every metric carries a provenance label. The growth agent is recommendation-only. Drafts are never auto-sent. |
| Reuse existing integrations | Supabase for Postgres, GitHub Actions for cron, Meta Cloud API for WhatsApp. |
| Secure by default | Production refuses to boot with placeholder secrets; the API fails closed when unconfigured. |

---

## 2. Layering

```
HTTP routes (app/api/routes)      thin: validation, status codes, auth wiring
        │
        ▼
Services (app/services)           all business rules live here; pure and testable
        │
        ▼
Models (app/db/models)            SQLAlchemy 2.0 typed mappings
        │
        ▼
Database                          SQLite (dev/test) or PostgreSQL (prod)
```

Rules that keep this honest:

* Routes never contain business logic — they translate errors into HTTP codes.
* Services never import FastAPI. That is why `lead_scoring.score_lead` can be
  unit-tested with no database and no HTTP.
* The database is the last line of defence: `CHECK` constraints, unique keys and
  foreign keys duplicate the important invariants.

---

## 3. Key decisions

### ADR-001 — SQLite for dev, PostgreSQL for production, one codebase
`DATABASE_URL` is the only difference. JSON columns use `JSON` with a `JSONB`
variant on PostgreSQL. Enums are stored as `VARCHAR` + `CHECK` rather than native
PostgreSQL enums, so the same migrations and models work on both engines.

*Consequence:* SQLite returns naive datetimes. Any code comparing timestamps
normalises the timezone first (see `followups._last_message_at` usage).

### ADR-002 — The migration is generated from the models
`scripts/generate_schema_sql.py` emits `migrations/001_init.sql` from the ORM
metadata, and `tests/test_migrations.py` re-generates it and asserts parity.

*Why:* hand-written DDL drifts. This was not theoretical — generating the DDL
revealed that SQLAlchemy 2.x defaults `Enum(create_constraint=False)`, meaning
the enum `CHECK` constraints were silently missing. The generator exposed it.

### ADR-003 — bcrypt directly, not passlib
passlib's last release was 2020 and its bcrypt backend raises on bcrypt ≥ 4.1
with inputs over 72 bytes. We call `bcrypt` directly and truncate at 72 bytes
explicitly and deterministically.

### ADR-004 — Two authentication paths, one authorisation model
`X-API-Key` (constant-time compared) for server-to-server work, and JWT for the
dashboard. Both resolve to a `Principal` with a role, so authorisation logic
exists once. If `ADMIN_API_KEY` is unset, protected endpoints return **503** —
the system fails closed rather than allowing anonymous admin access.

### ADR-005 — In-process rate limiting
A fixed-window limiter per client IP. No Redis, no extra cost, appropriate for a
single small instance. *Limitation:* it does not share state across workers or
instances. If you scale out, move the limit to the edge or to Redis.

### ADR-006 — Lead scoring is a transparent rule engine, not a model
A five-factor additive score with a per-factor explanation. Deterministic,
auditable, instant, free, and explainable to the business owner.

*Explicitly rejected:* training a model on a handful of leads would overfit and
could not be explained. The score is a triage heuristic, and every API response
says so.

### ADR-007 — Conservative extraction instead of guessing
The WhatsApp path parses the customer's own words for a service keyword, a
city/district and a time phrase, and only ever *fills blanks*. It never
overwrites what a human confirmed, and it never extracts price or availability.
Each extraction is recorded as a `signals_extracted` lead event with the
evidence, so a human can see exactly what was inferred and why.

### ADR-008 — Verification is a schema-level requirement
`bookings` carries `CHECK (status <> 'CONFIRMED' OR verified = true)`, and the
service layer raises `UnverifiedConfirmationError` → HTTP 409. Confirmation
requires a named human and a timestamp.

*Why:* the single most damaging failure for this business would be a customer
arriving for an appointment that was never actually available.

### ADR-009 — Drafts, not sends
Every automated reply — the WhatsApp first response and every follow-up — is
stored as a `Message` with status `DRAFTED`. `send_text` raises
`WhatsAppNotConfigured` while `WHATSAPP_DRY_RUN` is true (the default).

*Why:* automating the *drafting* captures almost all the time saving while
leaving the irreversible step to a person.

### ADR-010 — Follow-ups are idempotent and rate-limited
Every job carries an `idempotency_key` with a unique constraint. Processing
enforces: opt-out → cancel; consent not GRANTED → defer without consuming an
attempt; cooldown → defer; daily cap → defer; `max_attempts` → fail. Deferring
is preferred over cancelling so a job resumes when conditions change.

### ADR-011 — Metrics carry provenance
`measured` (counted from records), `recorded` (summed from values the business
entered), `not_recorded` (the data does not exist yet). The dashboard shows a
badge on every figure and a `measurement_notes` block stating what is *not*
tracked (walk-ins, off-platform spend).

*Why:* a dashboard that quietly presents a guess as a measurement destroys
trust in every other number on the page.

### ADR-012 — The growth agent cannot act
The agent is `recommendation_only`. Findings that would be consequential
(campaign budget changes) are flagged `requires_authorization` with a scope.
`POST /api/growth/authorizations` writes an audit record — it explicitly does
not perform the action. Nothing claims the system learns; it compares the
current period with the previous one and says when it cannot.

---

## 4. Request flow: an inbound WhatsApp message

```
Meta → POST /api/webhooks/whatsapp
  1. rate limit (webhook limiter)
  2. verify X-Hub-Signature-256 HMAC over the RAW body   → 401 if wrong
  3. parse Cloud API payload into InboundMessage objects
  4. per message:
       a. skip if wa_message_id already stored        (idempotent)
       b. resolve/create Contact by wa_id
       c. apply consent: STOP → OPTED_OUT, START → GRANTED
       d. get/create Conversation, store inbound Message
       e. find/create the WhatsApp Lead (dedupe_key = hash(wa_id|source))
       f. extract signals from the text, fill blanks only
       g. score → HOT/WARM/COLD, record lead_events
       h. if HOT → escalate the conversation to the owner
       i. build a DRAFTED reply (never sent)
  5. commit, return 200 fast so Meta does not retry
```

---

## 5. Threat model

| Threat | Mitigation |
|---|---|
| Stolen public Supabase key | RLS denies `anon` everything; the dashboard never talks to Supabase |
| Leaked service-role key | Only ever a server-side env var; asserted absent from the dashboard by a test |
| Forged WhatsApp webhook | HMAC signature required; 503 if no secret is configured |
| Credential stuffing | 10 logins/min per client; generic errors; equal-cost timing for unknown accounts |
| Duplicate/retried webhooks | `wa_message_id` unique constraint + early return |
| Duplicate leads | `dedupe_key` unique constraint + race handling on `IntegrityError` |
| Spam form submissions | Honeypot field → 202, nothing stored, generic response |
| XSS via CRM data in the dashboard | `textContent` only; a test asserts `.innerHTML` is absent |
| Accidental mass messaging | Dry-run default, consent gate, cooldown, daily cap, retry ceiling |
| Unverified bookings | Service exception + database CHECK constraint |
| Prompt/claim injection into marketing copy | Draft guard rejects unverifiable phrases; no prices in templates |

---

## 6. Known limitations (stated plainly)

1. **Rate limiting is per process.** Scaling to multiple workers weakens it.
2. **Follow-up scheduling depends on GitHub Actions cron**, which can be delayed
   at peak times. Delays are harmless here (jobs are idempotent) but the queue
   is not real-time.
3. **No outbound message queue.** Sending is manual by design for now.
4. **The growth agent has no memory of experiment outcomes**, so it cannot claim
   that a change improved anything. Implementing that is the natural next step.
5. **SQLite dev parity is close but not perfect** (naive datetimes, no JSONB).
   CI runs the suite on SQLite; run migrations against a real Postgres before
   trusting a schema change.
6. **Extraction is keyword-based.** It will miss phrasings it has not seen. It is
   deliberately conservative: a miss costs a clarification question, whereas a
   wrong guess would corrupt the record.
