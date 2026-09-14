# Dashboard milestone

The Next.js dashboard turns the existing shared-intelligence pipeline into a
reading workspace. It includes a paginated ranked feed, search, time and event-type
filters, full event analysis, source coverage, and saved topic preferences.
Sign-in uses Supabase Auth. Application profiles and preferences remain in the
existing PostgreSQL database. No Supabase database or service-role key is needed.

## Preview the interface

Requires Node.js 22.18+ (Node 24 is used in CI and Docker).

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000. The frontend example explicitly enables
`DASHBOARD_DEMO_MODE=true`. Demo mode uses illustrative stories and analysis,
displays a persistent label, and stores only sample topic choices in a browser
cookie. It never contacts FastAPI, Supabase, or an LLM provider. Live request errors
never fall back to demo content. A production preview can also use `npm run build`
followed by `npm start`; the start script packages the standalone static assets.

## Connect to the real pipeline

1. Create or select a Supabase project with email authentication enabled. Set its
   Site URL to `http://localhost:3000` for local development, and allow
   `http://localhost:3000/auth/callback` in the Auth redirect URLs. For a hosted
   instance, use its HTTPS origin and exact callback URL instead. Production email
   sign-in needs an appropriate Supabase SMTP configuration and sending limits.
2. In the existing root `.env`, set `SUPABASE_URL` and
   `SUPABASE_PUBLISHABLE_KEY` from that project. Leave the existing pipeline and
   database settings intact. Do **not** use a service-role key, and do not expose
   the operator key to the frontend. The provider's publishable/legacy anon key is
   the `apikey` header for Auth user validation.
3. Rebuild the backend and run the new migration:

   ```bash
   docker compose build api
   docker compose run --rm migrate
   docker compose up -d --force-recreate api
   ```

   For a host Python environment, run `alembic upgrade head` from `backend/` with
   its database environment loaded. Migration `0003_dashboard_users` creates
   `users` and `user_topics`; it does not change existing news or analysis rows.
4. Set these values in `frontend/.env.local`:

   ```dotenv
   DASHBOARD_DEMO_MODE=false
   BACKEND_URL=http://127.0.0.1:8000
   APP_URL=http://localhost:3000
   SUPABASE_URL=https://YOUR_PROJECT.supabase.co
   SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
   ```

   These are server environment settings. There is no browser Supabase client and
   no `NEXT_PUBLIC_` variable is required. Use the same Supabase project on both
   services. Restart the frontend after changing its environment.
5. Open the dashboard and request a sign-in link. Open the emailed link in the
   **same browser** so the PKCE verifier cookie is present. The first authenticated
   profile request creates a free application profile. Choose up to three topics
   in **My topics**, save, then open **Following**.

For a fully containerized local dashboard, configure the root `.env` values above,
keep `DASHBOARD_DEMO_MODE=false`, and run:

```bash
docker compose --profile dashboard up -d --build dashboard
```

The dashboard binds to localhost:3000 by default. `DASHBOARD_PORT` changes the host
port; change `APP_URL` and the Supabase redirect allowlist to match. Backend and
frontend containers run as UID 10001. Frontend runtime settings are supplied when
the container starts; the image build requires no credentials. The dashboard
container receives only its own configuration, not the pipeline's operator or
DeepSeek credentials.

## Identity and data boundaries

- Supabase handles account creation, magic links, PKCE exchange, and sessions.
  Next.js refreshes cookie sessions with the SSR package, verifies the current user
  with `getUser`, and forwards only that user's bearer token to FastAPI. The
  server-only session cookies are HttpOnly, SameSite=Lax, and Secure in production.
- FastAPI independently verifies every customer request against the configured
  Supabase `/auth/v1/user` endpoint. It requires an authenticated, non-anonymous
  account with a confirmed email. Invalid tokens return 401; provider outages and
  missing configuration fail closed. Only HTTPS is accepted for remote Auth URLs;
  loopback HTTP is allowed in development for local Supabase and tests.
- `GET /me`, `PUT /me/topics`, `GET /feed`, and `GET /feed/{id}` are customer
  endpoints. Existing `/clusters` and `/internal/*` remain operator-only inspection
  endpoints. This is the web dashboard API, not the deferred developer API product.
- Profile IDs come from verified Supabase identity. Callers cannot choose a user ID
  or subscription tier. Preferences are scoped by that ID. Replacements are
  transactional and serialize on the profile row; free accounts have a server-side
  three-topic limit. The database tier is authoritative. No paid upgrade flow or
  payment entitlement is created by this milestone.
- Customer payloads omit provider diagnostics and raw observation metadata.
  Authenticated responses are private and uncached. Source content renders as
  React text, and links accept only HTTP(S) URLs without embedded credentials.
- The configured PostgreSQL database belongs to the application backend. Do not
  expose these tables through a Supabase Data API without separately adding RLS
  and appropriate grants. Supabase is used for Auth only in this setup.

## Feed semantics

Search matches literal substrings in the primary title, event topic, and summary.
The eight topic choices map to documented keyword groups in
`backend/app/preferences.py`. They are broad delivery filters, not learned
classifications. Following matches any selected topic; no selection produces an
empty state. An explicit topic, search term, event type, and period further narrow
that result. Filters and counts apply before ranking and pagination.

The default period is the previous seven days. Today means the current UTC day;
the page labels that boundary. All-time removes the lower date bound. Future-dated
events are excluded. Rank order uses the existing shared editorial score and does
not run model calls or modify analysis. Source record count is distinct from
deduplicated article count. Missing summaries and analysis have explicit states.

## Verification

```bash
# From the repository root, install the backend test environment once.
python -m venv .venv
.venv/bin/pip install -r backend/requirements.lock
.venv/bin/pip install -e './backend[dev]'

cd frontend
npm ci
npm run test:unit
npm run build
npx playwright install chromium
npm test -- --workers=2
```

Playwright starts isolated servers on ports 3100–3102 and 3200. It covers desktop
and mobile flows, demo persistence, missing configuration, invalid callbacks,
and the real Next.js-to-FastAPI path with a test-only identity service and ephemeral
SQLite data. A deliberately forged embedded session user must not determine the
application profile. The production app has no test-token or SQLite bypass.

The backend suite covers Auth validation, tenant isolation, tier escalation
attempts, free-topic limits, filtering, and migration metadata. GitHub Actions also
runs real PostgreSQL/pgvector migration checks and builds both containers.

## Remaining delivery work

Live Supabase email delivery and a real account session require project
configuration; the implementation environment uses a test identity service.
Scheduled daily digests, email integration for those digests, Stripe subscriptions,
and real-time alerts are still pending. Existing source-coverage and editorial
quality follow-ups in the handoff remain relevant. No public deployment is created.

Implementation references: [Supabase SSR clients and session refresh](https://supabase.com/docs/guides/auth/server-side/creating-a-client?queryGroups=framework&framework=nextjs),
[Supabase email sign-in](https://supabase.com/docs/guides/auth/auth-email-passwordless),
[Next.js installation](https://nextjs.org/docs/app/getting-started/installation), and
[Next.js standalone output](https://nextjs.org/docs/app/api-reference/config/next-config-js/output).
