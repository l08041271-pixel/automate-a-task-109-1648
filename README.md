# MassageVIP Riyadh — AI Business Growth & Automation System

A low-cost, phone-friendly system that captures leads, qualifies them, supports
WhatsApp bookings, manages the customer relationship, tracks marketing
performance and continuously surfaces growth opportunities.

**Built incrementally, phase by phase, with every phase verified by tests.**
Current status: **123 automated tests passing, ruff clean.**

---

## 1. What it actually does today

| Capability | Status | Notes |
|---|---|---|
| Lead capture (web form, landing page, WhatsApp, social) | Working | `POST /api/leads`, dedupe enforced by a DB unique constraint |
| Explainable AI lead qualification | Working | 5-factor 0–100 score → HOT/WARM/COLD + missing info + next action |
| WhatsApp Business Platform webhook | Working | HMAC-verified, idempotent, opt-in/opt-out aware |
| WhatsApp replies | **Drafts only** | Nothing is auto-sent. `WHATSAPP_DRY_RUN=true` by default |
| CRM pipeline | Working | NEW → CONTACTED → QUALIFIED → BOOKED → COMPLETED → LOST |
| Bookings | Working | Confirmation is impossible without recorded human verification |
| Consent-aware follow-ups | Working | Drafts only; opt-out, cooldown, daily cap, retry limit enforced |
| Marketing content drafts | Working | 5 channels + UTM links; refuses unverifiable claims |
| CEO dashboard | Working | Mobile-first, served at `/dashboard` |
| Growth agent | Working | **Recommendation-only mode** |
| Supabase schema + RLS | Working | Generated from the ORM, validated as real PostgreSQL |
| Scheduled jobs (GitHub Actions) | Working | Follow-ups hourly, growth daily/weekly, health every 30 min |

### Things this system deliberately does NOT do

* It does not send WhatsApp messages on its own (dry-run by default).
* It does not confirm a booking without a human verifying availability.
* It does not invent prices, availability, reviews, testimonials or guarantees.
* It does not claim a button click identifies a person; anonymous leads stay anonymous.
* It does not claim to "learn" or "improve automatically" — it compares stored metrics.
* It does not publish marketing content.
* It does not scrape WhatsApp Web or use unofficial session access.

---

## 2. Architecture

```
        ┌──────────────────────────┐        ┌───────────────────────────┐
        │  Website form / landing  │        │  WhatsApp Business Cloud  │
        │  page / social campaign  │        │  (Meta) inbound webhook   │
        └────────────┬─────────────┘        └─────────────┬─────────────┘
                     │ POST /api/leads                    │ POST /api/webhooks/whatsapp
                     │ (rate-limited, honeypot)           │ (HMAC-verified, idempotent)
                     ▼                                    ▼
        ┌───────────────────────────────────────────────────────────────┐
        │                    FastAPI application (this repo)            │
        │  routes → services → SQLAlchemy models                        │
        │  • lead_scoring    (transparent 5-factor engine)              │
        │  • extraction      (echoes back only what the customer wrote) │
        │  • conversations   (contact → conversation → message → lead)  │
        │  • bookings        (verification-gated confirmation)          │
        │  • followups       (consent, cooldown, cap, retries)          │
        │  • analytics       (metrics with provenance)                  │
        │  • growth_agent    (recommendation-only analysis)             │
        │  • marketing       (draft content + tracking links)           │
        └───────┬───────────────────────────────┬───────────────────────┘
                │                               │
                ▼                               ▼
     ┌────────────────────┐          ┌─────────────────────────┐
     │ Supabase PostgreSQL│          │ Mobile-first dashboard  │
     │ 11 tables + RLS    │          │ /dashboard (static HTML)│
     └────────────────────┘          └─────────────────────────┘
                ▲
                │ scheduled, read/write
     ┌──────────┴─────────────────────────────────────────────────┐
     │ GitHub Actions: follow-ups (hourly) · growth agent (daily)  │
     │                 health check (30 min) · migrations (manual) │
     └────────────────────────────────────────────────────────────┘
```

**Trust boundaries.** The backend connects to Postgres with a privileged role
and bypasses RLS, so all authorisation is enforced in FastAPI. RLS is defence
in depth: `anon` gets no access at all, so even a leaked public key cannot read
CRM data. The Supabase service-role key is never sent to a browser or phone.

---

## 3. Project structure

```
.
├── app/
│   ├── main.py                     FastAPI app factory, CORS, request-id middleware
│   ├── core/
│   │   ├── config.py               pydantic-settings; fails fast on insecure prod config
│   │   ├── logging.py              JSON logging with redaction + correlation IDs
│   │   ├── phone.py                conservative E.164 normalisation
│   │   ├── rate_limit.py           in-process fixed-window limiter (no Redis needed)
│   │   └── security.py             bcrypt hashing, JWT, constant-time API key check
│   ├── db/
│   │   ├── base.py                 naming conventions + mixins
│   │   ├── enums.py                shared domain enums + pipeline transitions
│   │   ├── session.py              engine/session; SQLite dev, Postgres prod
│   │   └── models/                 crm.py · messaging.py · ops.py · auth.py
│   ├── schemas/                    pydantic request/response models
│   ├── services/                   business logic (see architecture above)
│   └── api/
│       ├── deps.py                 DB session, auth, roles, rate limits
│       └── routes/                 health · leads · auth · whatsapp · bookings
│                                   followups · analytics · growth
├── migrations/
│   ├── 001_init.sql                GENERATED from the ORM (11 tables + indexes)
│   └── 002_rls_and_triggers.sql    RLS policies, updated_at triggers, grants
├── scripts/
│   ├── generate_env.py             create .env with real secrets (mode 600)
│   ├── generate_schema_sql.py      regenerate 001_init.sql from the models
│   ├── apply_migrations.py         checksum-tracked migration runner
│   ├── create_owner.py             bootstrap the first owner account
│   ├── run_followups.py            hourly scheduled job (drafts only)
│   └── run_growth_agent.py         daily/weekly growth report
├── static/dashboard/               index.html · app.js · styles.css (no build step)
├── tests/                          123 tests across 13 files
├── ci/github-actions/              ci · healthcheck · followups · growth-agent · db-migrate
│                                   (install with scripts/install_workflows.py — see ci/README.md)
├── Dockerfile · Procfile · render.yaml
├── requirements.txt · requirements-dev.txt
├── ruff.toml · pytest.ini
└── .env.example                    every variable, placeholder values only
```

---

## 4. Quick start on Android (Termux)

Copy and paste. Tested command set for a fresh Termux install.

```bash
# --- 1. Base packages -------------------------------------------------------
pkg update && pkg upgrade -y
pkg install -y python git openssl libffi rust binutils

# --- 2. Get the code --------------------------------------------------------
git clone <YOUR_REPO_URL> massagevip
cd massagevip
git checkout cline/s25e7crg      # or main once merged

# --- 3. Virtual environment -------------------------------------------------
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

# --- 4. Generate your .env with real secrets --------------------------------
python scripts/generate_env.py
# Show the admin key when you need it:
grep ADMIN_API_KEY .env

# --- 5. Run the API ---------------------------------------------------------
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the interactive API and
`http://127.0.0.1:8000/dashboard` for the dashboard.

### Verify it works (second Termux session)

```bash
pkg install -y curl
curl -s http://127.0.0.1:8000/health
# {"status":"ok","version":"0.1.0","database":"ok",...}

# Create your owner login (prompts for a password):
python scripts/create_owner.py --email you@example.com --name "Owner"
```

### Run the tests

```bash
pip install -r requirements-dev.txt
ruff check app tests scripts
python -m pytest -q          # expect: 123 passed
```

> **Termux notes.** `rust`/`binutils` are only needed to build `pydantic-core`
> from source; recent Termux usually has a prebuilt wheel. If `psycopg` fails to
> build, you do not need it for local SQLite work — install it only when you
> connect to Supabase. Use Termux for development and testing; run the live
> service in the cloud (section 7) so the business is not dependent on a phone
> staying awake.

---

## 5. Environment variables

Full list with placeholders is in [`.env.example`](.env.example). Never commit a
real `.env`.

| Variable | Required | Purpose |
|---|---|---|
| `ENVIRONMENT` | yes | `development` \| `staging` \| `production`. Production refuses to boot with placeholder secrets |
| `DATABASE_URL` | yes | `sqlite:///./massagevip_dev.db` for dev; Supabase **pooled** Postgres URL for prod |
| `SECRET_KEY` | yes | Signs JWTs. Generate: `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `ADMIN_API_KEY` | yes | Server-to-server key. Endpoints fail closed (503) if unset |
| `BCRYPT_ROUNDS` | no | Password work factor. 12 in prod, 4 in tests |
| `CORS_ORIGINS` | yes | Comma-separated allowed dashboard origins |
| `RATE_LIMIT_PER_MINUTE` | no | General per-IP limit (default 60) |
| `WHATSAPP_VERIFY_TOKEN` | for WA | Meta webhook handshake token |
| `WHATSAPP_APP_SECRET` | for WA | Verifies `X-Hub-Signature-256`. Without it the webhook returns 503 |
| `WHATSAPP_ACCESS_TOKEN` | for sending | Cloud API token. Not needed while dry-run |
| `WHATSAPP_PHONE_NUMBER_ID` | for sending | Sender number id |
| `WHATSAPP_DRY_RUN` | no | **Defaults to true.** Must be explicitly disabled to send |
| `FOLLOWUP_COOLDOWN_HOURS` | no | Minimum gap between automated messages (default 24) |
| `FOLLOWUP_MAX_PER_DAY` | no | Hard cap per contact per 24h (default 2) |
| `FOLLOWUP_REQUIRE_CONSENT` | no | Require GRANTED consent (default true) |
| `UNANSWERED_INQUIRY_HOURS` | no | Delay before chasing (default 4) |
| `APPOINTMENT_REMINDER_HOURS_BEFORE` | no | Reminder lead time (default 24) |
| `FEEDBACK_DELAY_HOURS` | no | Delay before asking for feedback (default 2) |
| `BUSINESS_CITY` / `BUSINESS_TIMEZONE` / `BUSINESS_COUNTRY_CODE` | no | Riyadh / Asia/Riyadh / +966 |
| `HOT_SERVICE_KEYWORDS` | no | Core services (English + Arabic) used for scoring |
| `PUBLIC_BASE_URL` | yes in prod | Canonical **customer-facing** base URL used to build every UTM tracking link. Production refuses to boot with localhost/placeholder. |
| `BUSINESS_NAME` | no | Customer-facing brand. Signs every WhatsApp and follow-up draft, so it must match the storefront |

---

## 6. Database schema

11 tables. `migrations/001_init.sql` is **generated from the ORM** by
`scripts/generate_schema_sql.py`, so the SQL cannot drift from the code. A test
re-generates the DDL and asserts parity on every CI run.

| Table | Purpose | Key constraints |
|---|---|---|
| `contacts` | One row per unique person | unique `wa_id`, `phone_e164`, `email`; CHECK phone starts with `+` |
| `leads` | Captured inquiries + score | unique `dedupe_key`; CHECK `score BETWEEN 0 AND 100`; enum CHECKs |
| `campaigns` | Marketing campaigns + spend | unique (`utm_campaign`, `channel`) |
| `lead_events` | Append-only lead timeline | FK cascade on lead delete |
| `conversations` | WhatsApp threads | unique (`channel`, `wa_conversation_id`) |
| `messages` | Inbound + drafted outbound | unique `wa_message_id` (webhook idempotency) |
| `bookings` | Requests → confirmed → completed | **CHECK: `status <> 'CONFIRMED' OR verified = true`** |
| `follow_up_jobs` | Scheduled follow-ups | unique `idempotency_key`; index (`status`, `due_at`) |
| `automation_runs` | Growth agent / job history | — |
| `audit_logs` | Who did what | index (`entity_type`, `entity_id`) |
| `users` | Dashboard accounts | unique `email`; bcrypt hashes only |

**Row Level Security** (`002_rls_and_triggers.sql`): RLS is enabled on every
table, `anon` is revoked entirely, `authenticated` staff get scoped read/write,
deletes are never granted, and `updated_at` is maintained by trigger.

---

## 7. API reference

Interactive docs: `/docs` (Swagger) and `/redoc`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Liveness + DB check (used by CI and uptime monitors) |
| GET | `/health/live` | none | Cheap liveness, no DB |
| GET | `/health/ready` | none | Readiness |
| POST | `/api/leads` | none (rate-limited + honeypot) | Capture a lead. 201 new, 200 duplicate, 202 honeypot |
| GET | `/api/leads` | reader | List/filter leads (stage, classification, source, pagination) |
| GET | `/api/leads/{id}` | reader | Fetch one lead |
| PATCH | `/api/leads/{id}` | writer | Update; illegal stage transitions → 409 for STAFF (an OWNER may override) |
| POST | `/api/leads/{id}/score` | writer | Re-run qualification, return the full explanation |
| POST | `/api/bookings` | writer | Record a booking **request** |
| PATCH | `/api/bookings/{id}` | writer | Update; confirming without verification → 409 |
| GET | `/api/bookings/{id}` | writer | Fetch a booking |
| POST | `/api/webhooks/whatsapp` | HMAC signature | Inbound messages (idempotent) |
| GET | `/api/webhooks/whatsapp` | verify token | Meta handshake |
| GET | `/api/analytics/summary` | reader | All dashboard metrics with provenance |
| GET | `/api/follow-ups` | reader | Queue view |
| POST | `/api/follow-ups/run` | owner | Process due jobs → drafts only |
| POST | `/api/growth/run` | owner | Run growth analysis (recommends, never acts) |
| GET | `/api/growth/reports` | reader | Previous analyses |
| GET | `/api/growth/marketing-drafts` | reader | Draft content + tracking links |
| POST | `/api/growth/authorizations` | owner | Record approval for a consequential action |
| POST | `/api/auth/login` | none (rate-limited) | Get a JWT |
| GET | `/api/auth/me` | any | Who am I |
| POST/GET | `/api/auth/users` | owner | Manage dashboard users |
| GET | `/dashboard/` | — | The CEO dashboard |

**Roles:** `OWNER` (everything), `STAFF` (read + write CRM records), `VIEWER`
(read only). The `X-API-Key` header authenticates as OWNER for server-to-server
use.

---

## 8. Deployment

### 8.1 Create the Supabase project

1. Sign up at <https://supabase.com> (free tier is enough to start).
2. Create a project, choose the region closest to Riyadh.
3. **Settings → Database → Connection string → URI** and copy the **pooled**
   string (port `6543`). It looks like:
   `postgresql://postgres.<ref>:<PASSWORD>@aws-0-<region>.pooler.supabase.com:6543/postgres`
4. Paste it into `DATABASE_URL` in your hosting provider's environment
   (never into the repository).
5. **Settings → API** — copy the `anon` key and the `service_role` key. The
   service-role key goes **only** into the backend environment. It must never
   appear in the dashboard, a mobile app, or this repository.

### 8.2 Apply the schema

```bash
export DATABASE_URL="postgresql://postgres.<ref>:<pw>@...pooler.supabase.com:6543/postgres"
python scripts/apply_migrations.py --dry-run   # list what will run
python scripts/apply_migrations.py             # apply
```

You can also paste `migrations/001_init.sql` and then
`migrations/002_rls_and_triggers.sql` into the Supabase SQL editor.

The GitHub Actions workflow **Apply database migrations** does the same thing,
but only when you type `APPLY` to confirm — schema changes are never automatic.

### 8.3 Deploy the API (free tiers)

**Render** (blueprint included): push the repo, then *New → Blueprint* and pick
`render.yaml`. Render prompts for each secret. Free tier notes: the service
sleeps after ~15 minutes of inactivity and cold-starts on the next request
(roughly 30–60 s), and 750 instance-hours/month are shared across free services.

**Fly.io / Railway / Koyeb**: the included `Dockerfile` works anywhere:

```bash
docker build -t massagevip-api .
docker run --rm -p 8000:8000 --env-file .env massagevip-api
```

**Heroku-style PaaS**: a `Procfile` is included.

### 8.4 Set up the scheduled jobs

First install the workflow files (GitHub does not let an App token create
them, so they live in `ci/github-actions/`):

```bash
python scripts/install_workflows.py
git add .github/workflows
git commit -m "chore: enable scheduled workflows"
git push
```

Then configure the secrets below.

In GitHub → *Settings → Secrets and variables → Actions*:

| Kind | Name | Value |
|---|---|---|
| Secret | `DATABASE_URL` | Supabase pooled connection string |
| Secret | `SECRET_KEY` | same value as the API |
| Secret | `ADMIN_API_KEY` | same value as the API |
| Variable | `DEPLOY_BASE_URL` | e.g. `https://massagevip-api.onrender.com` |

Then the workflows run on their own:

| Workflow | Schedule | What it does |
|---|---|---|
| `ci.yml` | every push / PR | ruff, migration validation, 123 tests, boot smoke test |
| `healthcheck.yml` | every 30 min | fails loudly if `/health` is not `ok` |
| `followups.yml` | hourly | processes due follow-ups → **drafts only** |
| `growth-agent.yml` | daily 06:00 UTC + Monday | writes a report artifact and run summary |
| `db-migrate.yml` | manual | applies migrations after typing `APPLY` |

---

## 9. WhatsApp setup (when you are ready)

1. Create a Meta developer app and add the **WhatsApp** product.
2. Register a WhatsApp Business Account (WABA) and a business phone number.
3. In the app dashboard, set the webhook callback URL to
   `https://<your-api>/api/webhooks/whatsapp` and the verify token to your
   `WHATSAPP_VERIFY_TOKEN`. Subscribe to the `messages` field.
4. Copy the **App Secret** into `WHATSAPP_APP_SECRET` (this is what makes the
   signature check work) and the access token into `WHATSAPP_ACCESS_TOKEN`.
5. Put the phone number id in `WHATSAPP_PHONE_NUMBER_ID`.
6. **Leave `WHATSAPP_DRY_RUN=true`.** In this mode inbound messages are stored,
   leads are created and replies are drafted — but nothing is sent. Read the
   drafts, and only then decide to enable real sending.

Free-tier limits to expect: a test number can message a limited set of
recipients; production messaging requires business verification; and Meta bills
per 24-hour conversation once you leave the free allowance. Messaging rules
(opt-in, template approval, 24-hour service window) are enforced by Meta, not by
this code — this code simply refuses to message anyone who opted out.

### Required external accounts / approvals

| Need | Why | Cost |
|---|---|---|
| Supabase account | PostgreSQL + RLS | Free tier |
| GitHub account | source control + scheduled jobs | Free |
| Render/Fly/Railway account | persistent hosting | Free tier available |
| Meta developer app + WABA | WhatsApp Cloud API | Free to create; per-conversation fees later |
| Business verification (Meta) | production WhatsApp messaging | Free, but takes time to approve |
| Instagram / TikTok developer apps | publishing (not built yet) | Free |

---

## 10. How the lead score works

Five factors, 100 points, every point attributable:

| Factor | Max | What earns points |
|---|---|---|
| Service interest | 25 | Explicit core service (25), other explicit service (18), implied by the message (12), none (0) |
| Booking readiness | 25 | Pipeline stage (up to 25) +8 for a booking record +8 for appointment intent keywords (English and Arabic) |
| Preferred time | 20 | Exact time given (20), described in words (12), none (0) |
| Location compatibility | 15 | In the served city (15), outside it (5), unknown (8 — not heavily penalised) |
| Booking info completeness | 15 | Scaled over 5 required fields |

**HOT ≥ 70 · WARM 40–69 · COLD < 40.**

The API returns the score, the per-factor breakdown, the missing information and
a recommended next action. Every response includes this disclaimer:

> Score is a heuristic triage value based on the information provided. It is not
a prediction that the customer will book.

---

## 11. Backups and recovery

**Supabase** — *Database → Backups*. The free tier keeps daily backups for a
limited window; check the current retention in your dashboard before relying on
it. For a portable copy at any time:

```bash
# Logical dump (schema + data)
pg_dump "$DATABASE_URL" --no-owner --format=custom --file="backup-$(date +%F).dump"

# Restore into a fresh database
pg_restore --no-owner --clean --if-exists --dbname="$DATABASE_URL" "backup-2025-01-01.dump"
```

**Before any migration**, take a dump. The migration runner records a checksum
per file in `schema_migrations` and warns if an applied file changes later.

**Recovery drill (do this once so you know it works):**

```bash
createdb restore_test
pg_restore --no-owner --dbname=restore_test backup-latest.dump
DATABASE_URL=postgresql://localhost/restore_test python -m pytest -q
```

**What is NOT backed up by this repo:** the `.env` file, your Supabase password,
and the WhatsApp access token. Store those in a password manager. Losing the
`SECRET_KEY` invalidates all dashboard sessions (users simply log in again).

---

## 12. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `RuntimeError: Refusing to start in production with insecure config` | `ENVIRONMENT=production` with placeholder/short secrets or SQLite | Generate real secrets and a Postgres `DATABASE_URL` |
| Protected endpoints return **503** | `ADMIN_API_KEY` is not set | Set it; the API fails closed on purpose |
| Protected endpoints return **401** | Wrong/missing `X-API-Key` or expired JWT | Log in again via `/api/auth/login` |
| `POST /api/leads` returns **422** | Phone not normalisable, bad email, or an unknown field | Send E.164 or a local Saudi number; check `extra="forbid"` fields |
| Duplicate submission returns **200**, not 201 | Dedupe worked: same person + same source | Expected. Change `source` for a genuinely new inquiry |
| WhatsApp webhook returns **503** | `WHATSAPP_APP_SECRET` unset | Set it — unverified input is never trusted |
| WhatsApp webhook returns **401** | Signature mismatch | Use the app secret, and sign the **raw** body bytes |
| Messages stay in `DRAFTED` | By design — nothing is auto-sent | Send manually, or enable sending deliberately |
| `409` on `PATCH /api/bookings/{id}` | Confirming without `verified=true` | Verify availability with staff first, then set `verified: true` |
| Follow-ups never fire | No GRANTED consent, or `no_whatsapp_channel` | Check `GET /api/follow-ups` and the `last_error` column |
| `429 Too Many Requests` | Rate limit hit | Wait for `Retry-After`, or raise `RATE_LIMIT_PER_MINUTE` |
| Migration says *checksum drift* | An applied `.sql` file was edited | Add a new migration instead of editing an applied one |
| Render service is slow on first request | Free tier sleeps | Expected; use `/health` to warm it before a demo |
| `Refusing to start in production...PUBLIC_BASE_URL` | Still localhost/placeholder | Set it to your real primary storefront domain |
| Drafts are signed with the wrong brand | `BUSINESS_NAME` not updated | Set it to match the storefront the customer sees |
| Campaign links point at localhost | `PUBLIC_BASE_URL` left at its dev value | Set the production env var; see section 5 |
| `pip` SSL errors on a restricted network | Corporate/proxy CA | `pip install --cert /path/to/ca.pem -r requirements.txt` |
| `psycopg` build fails on Termux | Missing build tools | `pkg install binutils`; SQLite works without `psycopg` |

Run the built-in diagnostics first:

```bash
curl -s http://127.0.0.1:8000/health | python -m json.tool
python scripts/apply_migrations.py --dry-run
python -m pytest -q
```

---

## 13. Security checklist

- [x] No credentials in source control — `.env` is git-ignored, `.env.example`
      holds placeholders only.
- [x] Secrets generated locally by `scripts/generate_env.py` (mode 600).
- [x] Production refuses to start with placeholder secrets or SQLite.
- [x] Passwords hashed with bcrypt; never returned by the API.
- [x] Constant-time API-key comparison; unknown-account logins burn equal CPU.
- [x] Login is rate-limited to 10 attempts/minute per client.
- [x] WhatsApp webhooks require a valid HMAC signature.
- [x] Input validation with `extra="forbid"` on every write schema.
- [x] Structured JSON logs with token/phone redaction.
- [x] Audit trail for logins, user creation, growth runs and authorisations.
- [x] RLS enabled on all tables; `anon` revoked; service-role key server-side only.
- [x] Dashboard renders CRM data with `textContent`, never `innerHTML`.
- [x] No phone numbers, names or keys committed as fixtures.

---

## 14. Roadmap

Phases 1–9 are complete. Natural next steps, in priority order:

1. **Enable real WhatsApp sending** once Meta verification completes, and turn
   `WHATSAPP_DRY_RUN=false` — behind a review of the draft templates.
2. **Draft-review UI** so staff can approve/send queued drafts from the phone.
3. **Instagram/TikTok publishing** once those apps are connected and approved.
4. **Experiment tracking**: the growth agent already proposes experiments;
   storing their outcomes would let it genuinely evaluate results over time.
5. **Revenue targets** so the dashboard can show progress against a plan.

---

## 15. Phase log (what was verified, when)

| Phase | Deliverable | Verification |
|---|---|---|
| 1 | API + lead-scoring engine | 44 tests, live uvicorn smoke test |
| 2 | Supabase schema + RLS | SQL parsed as real PostgreSQL (pglast); migration/model parity test |
| 3 | Auth + security | 57 tests incl. brute-force 429 and audit trail |
| 4 | WhatsApp webhook | 78 tests; dry-run send refused; drafts asserted claim-free |
| 5 | Follow-ups + bookings | 100 tests; guard-rails proven (opt-out, cooldown, cap, retries) |
| 6+7 | Analytics + dashboard | 108 tests; live login → analytics → dashboard verified |
| 8 | Growth agent + marketing | 123 tests; CLI run verified on a scratch DB |
| 9 | CI, deployment, docs | workflows YAML-validated; full 16-step live E2E; a real timezone bug found and fixed |

---

## 16. Licence and ownership

Private project. Contains no third-party customer data. Replace the placeholder
business details (`BUSINESS_CITY`, `PUBLIC_BASE_URL`, service keywords) with
real values before going live.
