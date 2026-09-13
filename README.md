# AI News Aggregator

The first implementation milestone from `SPEC.md`: fetch AI news, retain source evidence, deduplicate articles, and group related coverage into persistent events.

This is a backend pipeline foundation. The two-pass analysis, customer accounts, Next.js dashboard, email delivery, and Stripe billing are the next milestones. There is no deployed service yet.

## Implemented

| Component | Behavior |
| --- | --- |
| ArXiv | Atom API ingestion for cs.AI, cs.LG, cs.CL, cs.CV; paged, bounded lookback; requests spaced at least 3.1 seconds apart |
| Hacker News | Firebase top stories; title/body/link AI filtering; retains story ID, discussion URL, points, and comments |
| Company RSS | Ten configured feeds; RSS/Atom parsing; ETag and Last-Modified support |
| Article parsing | Feed/API text first; optional trafilatura extraction with per-origin robots rules checked again on redirects |
| Deduplication | Canonical URL SHA-256 plus conservative 64-bit SimHash for long bodies; durable aliases and source observations |
| Embeddings | CPU MiniLM, 384 dimensions; pinned model revision; batch processing and resume after failure |
| Event clustering | Cosine threshold 0.85 within a 72-hour event window; authority-first primary article selection |
| Persistence | SQLAlchemy, Alembic, PostgreSQL/pgvector, timezone-aware timestamps, membership constraints, run status |
| Scheduling | Celery and Redis; 30-minute default interval; PostgreSQL advisory lock prevents overlapping writers |
| Inspection | Protected FastAPI endpoints for clusters, source health, and recent runs; public liveness/readiness |

## Start with Docker

Requires Docker Engine/Desktop with Compose v2. The checked-in dependency locks target Python 3.12 and Linux CPU execution. The first image build installs PyTorch; the first model warmup downloads MiniLM. No paid API keys are needed for this milestone.

From this project's root:

```bash
cp .env.example .env
```

Set `OPERATOR_API_KEY` in `.env` to a random value. You can generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. This only protects the development inspection API. Customer authentication will use Clerk or Supabase as specified.

```bash
docker compose build
docker compose up -d postgres redis api
docker compose run --rm api ai-news check-sources
docker compose run --rm api ai-news warm-model
docker compose run --rm api ai-news ingest
```

The API depends on completed migration and source-seeding services. `check-sources` exits nonzero if a source fails, and `ingest` exits nonzero for a partial run while keeping successfully ingested records. Inspect source/run errors before proceeding if either command reports failures.

Open [the API documentation](http://localhost:8000/docs). Inspect a first result:

```bash
curl http://localhost:8000/health/ready
curl -H 'X-Operator-Key: YOUR_OPERATOR_API_KEY' http://localhost:8000/clusters
curl -H 'X-Operator-Key: YOUR_OPERATOR_API_KEY' http://localhost:8000/internal/runs
```

Once the first run succeeds, start regular ingestion:

```bash
docker compose up -d worker beat
docker compose logs --tail=50 worker
```

Compose binds API, PostgreSQL, and Redis to localhost. Its database credentials are local-development defaults. Named volumes retain the database, model cache, and scheduler state. `docker compose down` stops the stack without deleting these volumes.

If port 5432 is occupied, set `POSTGRES_PORT=55432` in `.env` and change the local `DATABASE_URL` port to 55432 as well. Services inside Compose still connect to PostgreSQL on 5432.

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

Create that disposable database first. `.github/workflows/test.yml` provisions it with pgvector and runs all tests in GitHub Actions. The workflow has been authored but has not been executed on a remote repository.

See [validation results](docs/VALIDATION.md) for checks actually performed in the implementation environment.

## Data and processing decisions

- **Shared event intelligence:** source articles and clusters are global. No per-user analysis or fabricated analysis is generated; `summary` and `analysis` remain null until Week 3.
- **Provenance survives deduplication:** one article can have several source observations. `cluster_size` counts distinct article records; it does not count publishers. Later diversity scoring must use observations and source categories, and avoid treating syndication as independent corroboration.
- **Safe replays:** URL aliases and `(source_id, external_id)` observations prevent duplicate ingestion; engagement signals are updated in place. RSS validators only advance after all returned items are handled successfully.
- **Recoverable work:** articles commit before embeddings. Missing embeddings and cluster memberships resume on the next run. A source failure does not discard another source's successful fetch.
- **Model consistency:** the database stores a 384-dimensional vector and model/revision identity. Changing to the spec's 1,536-dimensional OpenAI alternative requires a migration and full re-embedding/reclustering.
- **Representative selection:** source authority dominates body completeness. Authority scores are editable initial judgments, not measured quality. A higher-authority original can replace a syndicated copy while preserving its old URL alias.
- **News snapshots:** each run reads up to `SOURCE_LIMIT` records per source, with a rolling `INITIAL_LOOKBACK_DAYS` filter. This does not guarantee exhaustive capture during high-volume periods or recover every item missed during a long outage.
- **Conservative clustering:** short texts bypass SimHash; clustering compares an article with recent primary articles. The initial threshold favors precision. Week 3 should evaluate labeled events before tuning or upgrading to HDBSCAN.
- **Fetching boundaries:** requests have time/size limits, retries, pacing, public-address checks, and validated redirects. The fetcher uses direct connections. DNS is checked before each URL fetch; production egress controls should also prevent DNS rebinding. Failed or unreadable robots policies leave feed/API text intact.

## Next milestones

1. Run the full stack on a Docker-capable host; complete the PostgreSQL gate, source checks, and one real ingestion run. Review clustered events and resolve remaining source coverage gaps.
2. **Week 3:** implement cluster-input hashing and two-pass summary/structured analysis, record model/prompt versions and costs, add ranking, evaluate HDBSCAN against labeled events. Personalization remains outside shared analysis.
3. **Week 4:** Clerk/Supabase user identity, topic preferences and tier limits, Next.js dashboard, local-time daily digests, Resend/Postmark, Stripe subscriptions and verified webhooks.

Post-MVP features in the specification, including developer API access, Reddit, GitHub Trending, bots, and team plans, remain deferred. The spec lists developer API endpoints elsewhere; the explicit Post-MVP exclusion takes precedence here.

## Source references

The registry, coverage gaps, and live probe results are documented in [SOURCES.md](docs/SOURCES.md).

- [ArXiv API manual](https://info.arxiv.org/help/api/user-manual.html) and [API terms/rate limits](https://info.arxiv.org/help/api/tou.html)
- [Official Hacker News Firebase API](https://github.com/HackerNews/API)
- [pgvector Python/SQLAlchemy integration](https://github.com/pgvector/pgvector-python) and [pgvector indexing](https://github.com/pgvector/pgvector)
- [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)

Thank you to arXiv for use of its open access interoperability.
