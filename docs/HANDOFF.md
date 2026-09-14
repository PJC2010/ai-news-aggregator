# Project handoff — updated 2026-09-14

Repository: https://github.com/PJC2010/ai-news-aggregator

## Current milestone

The next delivery slice adds the Next.js dashboard, Supabase Auth integration,
per-user PostgreSQL profiles and topics, and authenticated customer feed endpoints.
See [DASHBOARD.md](DASHBOARD.md) for demo and live setup. Migration
`0003_dashboard_users` is required for the customer endpoints. Browsing and changing
topics do not run paid analysis. The three-topic free limit is enforced by the
backend; no client input can set a subscription tier. This environment verifies
the complete browser-to-FastAPI flow against a test identity service. A real
Supabase project and email sign-in still need to be configured and checked.

The local Colima notes below record the earlier backend environment; they do not
describe a deployment performed by this dashboard change.

The downloaded Week 1–2 backend is connected to its private GitHub repository. Ingestion, source observations, deduplication, MiniLM embeddings, and event clustering are implemented. The shared-intelligence milestone now adds:

- DeepSeek Flash summaries and V4 Pro structured analysis, stored once per shared event.
- Deterministic evidence/model/prompt/output-limit hashes and stage caches. A failed second pass can reuse the successful first pass.
- Strict JSON schemas, source-grounded code/paper links, explicit evidence limitations, and an insufficient-evidence state for headline-only events.
- Durable attempt journals, token usage, versioned peak-rate cost estimates, conservative reservations for unknown usage, and a configurable per-run spending limit.
- Recency, significance, source-diversity, and deduplicated HN engagement ranking, with components visible through the API.
- Publisher corrections with text provenance preserved; changes invalidate embeddings and shared analysis.
- Mistral's official RSS feed and an official ArXiv RSS fallback. ArXiv fallback remains `partial` because it cannot recover the full requested lookback.

Migration `0002_cluster_analysis` adds analysis history and status plus article text-kind metadata. Historical bodies begin as `unknown` and are protected from replacement by shorter feed excerpts. An identical re-fetch from the same publisher establishes the text kind for future corrections.

## Local setup and operation

- Python 3.12 environment: `.venv/`. Ignored root `.env` contains runtime settings, the operator key, and the configured DeepSeek key.
- Colima profile/context: `ai-news` / `colima-ai-news`, QEMU with 2 CPUs and 4 GiB RAM.
- PostgreSQL uses localhost:55432 because an unrelated host PostgreSQL occupies 5432. Compose services use postgres:5432 internally. Redis uses localhost:6379.
- API, PostgreSQL, and Redis run locally. Regular `worker` and `beat` services remain stopped while source coverage is being reviewed. Automatic paid analysis defaults to off.
- API documentation: http://localhost:8000/docs. Use the `X-Operator-Key` header for cluster, source, and analysis inspection.

From the project root:

```bash
colima start --profile ai-news --vm-type qemu
docker context use colima-ai-news
docker compose build api
docker compose up -d --wait api
docker compose exec -T api ai-news analyze --limit 1
```

Build the shared backend image once; do not build all Python services separately. Existing database and model volumes survive `docker compose down`.

Manual analysis uses `ANALYSIS_BUDGET_USD=0.25` per run by default. Override it for a bounded check:

```bash
docker compose exec -T -e ANALYSIS_BUDGET_USD=0.05 api ai-news analyze --limit 1
docker compose exec -T api ai-news analyze --cluster-id EVENT_UUID
```

Inspect `GET /internal/analysis` for configuration status, recent runs, cache outcomes, models, tokens, and costs. Provider billing is authoritative; displayed amounts are estimates. Do not print or commit `.env`.

To enable scheduling later, start `worker` and `beat`. To include paid analysis in each scheduled run, explicitly set `ANALYSIS_ENABLED=true` and recreate the worker. Its budget is per run, not a daily or monthly allowance.

Run the checks from `backend/`:

```bash
TEST_DATABASE_URL=postgresql+psycopg://news:news@127.0.0.1:55432/news_test ../.venv/bin/pytest -q
../.venv/bin/ruff check app tests migrations
../.venv/bin/ruff format --check app tests migrations
```

## Live evidence

The database contains 39 articles, embeddings, cluster memberships, and observations across 13 configured sources. The latest bounded ingestion added five articles and retained an explicit ArXiv RSS coverage warning; all other sources completed. Generated analysis was validated on one real AWS event. Replaying its unchanged evidence completed with no new calls and zero incremental estimated cost. Exact run and billing-estimate evidence is recorded in [VALIDATION.md](VALIDATION.md).

## Remaining work

1. Review summaries, classifications, ranking, and clustering against a labeled event sample. No HDBSCAN or clustering threshold change is justified yet. Generated analysis needs editorial quality evaluation beyond a single smoke event.
2. Recover full ArXiv lookback coverage and add verified Anthropic, Meta AI, and Cohere sources. RSS fallback can legitimately be empty on weekends. See [SOURCES.md](SOURCES.md).
3. Configure and verify real Supabase email sign-in using the new dashboard. Then add local-time digests, email delivery, and subscriptions with verified webhooks. Dashboard topic matching is currently a documented keyword filter.
4. Before production: move secrets into deployment settings, add appropriate access control, evaluate source outage recovery and large-scale performance, and replace in-memory global ranking with an indexed serving strategy.

The customer frontend and Supabase authentication integration are implemented.
Live Auth setup, digest email delivery, billing integration, and public deployment
remain pending.
