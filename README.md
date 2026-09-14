# AI News Aggregator

The shared news pipeline from `SPEC.md`: fetch AI news, retain source evidence, deduplicate articles, group related coverage, and generate reusable event summaries and analysis.

This is a working dashboard and backend preview. The Next.js reading workspace includes Supabase sign-in, ranked events, full analysis, and saved topic preferences. Live sign-in requires configuring a Supabase project. Digest email delivery and Stripe billing remain future milestones. There is no publicly deployed service yet.

## Try the dashboard

With Node.js 22.18+:

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000 for the clearly labeled demo workspace. It uses illustrative stories and requires no credentials. See [dashboard setup](docs/DASHBOARD.md) to connect Supabase Auth and the real pipeline, use Docker, or run the browser integration tests.

## Implemented

| Component | Behavior |
| --- | --- |
| ArXiv | Bounded Atom API ingestion for cs.AI, cs.LG, cs.CL, cs.CV; official RSS fallback for temporary failures, explicitly marked as limited coverage |
| Hacker News | Firebase top stories; title/body/link AI filtering; retains story ID, discussion URL, points, and comments |
| Company RSS | Eleven configured feeds, including Mistral; RSS/Atom parsing; ETag and Last-Modified support |
| Article parsing | Feed/API text first; optional trafilatura extraction with per-origin robots rules checked again on redirects |
| Deduplication | Canonical URL SHA-256 plus conservative 64-bit SimHash for long bodies; durable aliases and source observations |
| Embeddings | CPU MiniLM, 384 dimensions; pinned model revision; batch processing and resume after failure |
| Event clustering | Cosine threshold 0.85 within a 72-hour event window; authority-first primary article selection |
| Shared intelligence | DeepSeek Flash summary followed by V4 Pro structured analysis; schema and evidence-link validation, versioned cache, usage and estimated costs |
| Ranking | Explainable recency, technical significance, independent publisher/category diversity, and deduplicated Hacker News engagement |
| Persistence | SQLAlchemy, Alembic, PostgreSQL/pgvector, timezone-aware timestamps, membership constraints, run status |
| Scheduling | Celery and Redis; 30-minute default interval; PostgreSQL advisory lock prevents overlapping writers |
| Inspection | Protected FastAPI endpoints for clusters, source health, and recent runs; public liveness/readiness |
| Dashboard | Responsive Next.js feed, search, filters, pagination, event analysis, and source coverage |
| Identity and preferences | Supabase email sign-in; PostgreSQL-backed profiles and isolated topic selections; three-topic free limit |

## Start with Docker

Requires Docker Engine/Desktop with Compose v2+. The checked-in dependency locks target Python 3.12 and Linux CPU execution. The first image build installs PyTorch; the first model warmup downloads MiniLM. Ingestion and embeddings run without paid API keys; generated analysis requires a DeepSeek API key and account balance.

From this project's root:

```bash
cp .env.example .env
```

Set `OPERATOR_API_KEY` in `.env` to a random value. You can generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. This only protects the development inspection API. Customer authentication will use Clerk or Supabase as specified.

```bash
docker compose build api
docker compose up -d postgres redis api
docker compose run --rm api ai-news check-sources
docker compose run --rm api ai-news warm-model
docker compose run --rm api ai-news ingest
```

All Python services reuse the backend image built by `docker compose build api`. The API depends on completed migration and source-seeding services. `check-sources` exits nonzero if a source fails, and `ingest` exits nonzero for a partial run while keeping successfully ingested records. Inspect source/run errors before proceeding if either command reports failures.

Open [the API documentation](http://localhost:8000/docs). Inspect a first result:

```bash
curl http://localhost:8000/health/ready
curl -H 'X-Operator-Key: YOUR_OPERATOR_API_KEY' http://localhost:8000/clusters
curl -H 'X-Operator-Key: YOUR_OPERATOR_API_KEY' http://localhost:8000/internal/runs
```

After reviewing source health and coverage limitations, regular ingestion can be started with:

```bash
docker compose up -d worker beat
docker compose logs --tail=50 worker
```

Compose binds API, PostgreSQL, and Redis to localhost. Its database credentials are local-development defaults. Named volumes retain the database, model cache, and scheduler state. `docker compose down` stops the stack without deleting these volumes.

If port 5432 is occupied, set `POSTGRES_PORT=55432` in `.env` and change the local `DATABASE_URL` port to 55432 as well. Services inside Compose still connect to PostgreSQL on 5432.

## Generate shared analysis

Create a key in [DeepSeek's API keys dashboard](https://platform.deepseek.com/api_keys) and place it in the ignored root `.env` as `DEEPSEEK_API_KEY`. API billing is managed in [the DeepSeek platform](https://platform.deepseek.com/). Recreate running services after changing `.env` so they receive the new settings:

```bash
docker compose up -d --force-recreate api
docker compose exec -T api ai-news analyze --limit 1
```

The default summary model is `deepseek-flash`; structured analysis uses `deepseek-v4-pro`. Each run processes up to `ANALYSIS_CLUSTER_LIMIT=10` uncached clusters, with `ANALYSIS_BUDGET_USD=0.25` as a conservative pre-request spending limit. To resume or verify a specific event, use `ai-news analyze --cluster-id UUID`. Cached stages require no new model request; completed events with unchanged evidence, models, prompts, and output limits are skipped. At least 40 words of source text are required. Headline-only events stay explicitly marked as insufficient evidence.

`GET /internal/analysis`, protected with the operator key, shows configuration status, recent runs, model/prompt versions, tokens, and estimated costs. It never returns credentials. Costs use the recorded [DeepSeek peak rates](https://api-docs.deepseek.com/quick_start/pricing/) and token usage; they are estimates, not invoices. Unknown-usage failures retain a conservative reservation. Requests are not automatically retried after a provider error. Changing prices requires updating the versioned rate table.

Automatic analysis is off by default. Setting `ANALYSIS_ENABLED=true` and recreating `worker` attaches analysis to each scheduled ingestion. The budget applies **per run**, not per day or month. Manual analysis works with this setting off.

`GET /clusters` and `/clusters/today` default to ranked order; use `?sort=latest` for chronological order. Responses expose rank components and analysis status, alongside summaries and structured analysis when available. Missing significance receives a marked neutral value. Ranking currently loads the filtered candidate set in memory, suitable for this local preview; large-scale serving needs a precomputed or database-backed ranking index.

## Develop without containerizing Python

Use Python 3.12 for the tested lock files. Python 3.11+ is the package compatibility floor; alternative versions/platforms should resolve dependencies from `pyproject.toml` and run the tests.

```bash
cp .env.example .env
docker compose up -d postgres redis
python -m venv .venv
source .venv/bin/activate
cd backend
pip install -r requirements.lock
pip install -e '.[local,dev]'
```

The optional `local` extra installs a platform-appropriate PyTorch. Linux CPU users can instead install the full pinned `requirements-local.txt` with `--extra-index-url https://download.pytorch.org/whl/cpu` before installing `.[dev]`.

Environment variables override `.env`. For shell development, copy the root `.env` into `backend/.env` or export its values before running the commands below; configuration is loaded from the current working directory.

```bash
alembic upgrade head
ai-news seed
ai-news warm-model
ai-news ingest
uvicorn app.main:app --reload
```

Separate worker terminals can run:

```bash
celery -A app.workers.tasks:celery_app worker --loglevel=info --concurrency=1
celery -A app.workers.tasks:celery_app beat --loglevel=info
```

## Verify changes

From `backend/`, with the development extra installed:

```bash
ruff check app tests migrations
ruff format --check app tests migrations
pytest -q
alembic upgrade head --sql
```

The default tests use in-memory SQLite and controlled fetch/embedding fixtures to check application behavior. SQLite is not an application deployment option. A separate test exercises the real PostgreSQL migration, schema comparison, pgvector storage, and advisory locking when `TEST_DATABASE_URL` points to a disposable database whose name ends in `_test`:

```bash
TEST_DATABASE_URL=postgresql+psycopg://news:news@localhost:5432/news_test pytest -q -m postgres
```

Create that disposable database first. `.github/workflows/test.yml` provisions it with pgvector and runs all tests in GitHub Actions. It also builds the backend image and checks its non-root runtime user. The initial test workflow passed on GitHub; see the validation log for subsequent build and runtime results.

See [validation results](docs/VALIDATION.md) for checks actually performed in the implementation environment.

## Data and processing decisions

- **Shared event intelligence:** source articles, clusters, summaries, and analysis are global. Personalization belongs at delivery time. Evidence is bounded to the primary article plus three supporting articles. Source text is treated as untrusted data, and returned code/paper links must appear in the supplied evidence allowlist.
- **Provenance survives deduplication:** one article can have several source observations. `cluster_size` counts distinct article records. Ranking derives diversity from observations and categories, caps it by distinct articles, and avoids rewarding duplicate HN story IDs.
- **Safe replays:** URL aliases and `(source_id, external_id)` observations prevent duplicate ingestion; engagement signals are updated in place. RSS validators only advance after all returned items are handled successfully.
- **Recoverable work:** articles commit before embeddings. Missing embeddings and cluster memberships resume on the next run. A source failure does not discard another source's successful fetch.
- **Model consistency:** the database stores a 384-dimensional vector and model/revision identity. Changing to the spec's 1,536-dimensional OpenAI alternative requires a migration and full re-embedding/reclustering.
- **Representative selection:** source authority dominates body completeness. Authority scores are editable initial judgments, not measured quality. A higher-authority original can replace a syndicated copy while preserving its old URL alias.
- **Publisher corrections:** updates from the representative publisher can replace equal-length or shorter text of the same kind, and update its title. Full feed content, extracted articles, and abstracts can correct prior text; a shorter summary cannot overwrite a known full article or legacy body. Changes invalidate embeddings and cluster intelligence for regeneration.
- **News snapshots:** each run reads up to `SOURCE_LIMIT` records per source, with a rolling `INITIAL_LOOKBACK_DAYS` filter. This does not guarantee exhaustive capture during high-volume periods or recover every item missed during a long outage.
- **Conservative clustering:** short texts bypass SimHash; clustering compares an article with recent primary articles. The initial threshold favors precision. Week 3 should evaluate labeled events before tuning or upgrading to HDBSCAN.
- **Fetching boundaries:** requests have time/size limits, retries, pacing, public-address checks, and validated redirects. The fetcher uses direct connections. DNS is checked before each URL fetch; production egress controls should also prevent DNS rebinding. Failed or unreadable robots policies leave feed/API text intact.

## Next milestones

1. Review live summaries and ranking against a labeled event sample; evaluate clustering changes before adopting HDBSCAN. Improve ArXiv lookback recovery and add verified Anthropic, Meta AI, and Cohere adapters. See [the handoff](docs/HANDOFF.md).
2. **Week 4:** Configure and verify live Supabase email sign-in, then add local-time daily digests, Resend/Postmark, Stripe subscriptions and verified webhooks. The dashboard, Supabase integration, and saved topic preferences are implemented; see [dashboard setup](docs/DASHBOARD.md).

Post-MVP features in the specification, including developer API access, Reddit, GitHub Trending, bots, and team plans, remain deferred. The spec lists developer API endpoints elsewhere; the explicit Post-MVP exclusion takes precedence here.

## Source references

The registry, coverage gaps, and live probe results are documented in [SOURCES.md](docs/SOURCES.md).

- [ArXiv API manual](https://info.arxiv.org/help/api/user-manual.html) and [API terms/rate limits](https://info.arxiv.org/help/api/tou.html)
- [Official Hacker News Firebase API](https://github.com/HackerNews/API)
- [pgvector Python/SQLAlchemy integration](https://github.com/pgvector/pgvector-python) and [pgvector indexing](https://github.com/pgvector/pgvector)
- [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)

Thank you to arXiv for use of its open access interoperability.
