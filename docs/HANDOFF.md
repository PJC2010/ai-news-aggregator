# Project handoff — 2026-09-13

## Where work resumed

The earlier ChatGPT task implemented the Week 1–2 pipeline, created the private `PJC2010/ai-news-aggregator` repository, and stopped at a blocked upload. The downloaded folder did not contain Git history. This local follow-up connected it to the repository's existing `main` history and uploaded the complete implementation.

Repository: https://github.com/PJC2010/ai-news-aggregator

## Changes made during local validation

- Fixed double decoding of compressed HTTP responses; six previously failing feeds now parse successfully.
- Bounded SimHash matching on both sides of its seven-day window, preventing old events from merging with much newer copies.
- Fixed the Docker image's `news` account-name collision by using the dedicated `ainews` user at UID 10001.
- Made all Python services share one backend image. Build it once with `docker compose build api`.
- Made the PostgreSQL host port configurable. This Mac uses 55432 because another PostgreSQL server already occupies 5432.
- Added regression tests and GitHub Actions checks for the production image and its non-root user.

## Local setup

- Python 3.12 environment: `.venv/`; runtime settings and generated operator key: ignored `.env`.
- Colima profile/context: `ai-news` / `colima-ai-news`, using QEMU with 2 CPUs and 4 GiB RAM.
- Docker Compose and Buildx are installed in the user's Docker CLI plugin directory. Stale Docker Desktop links and credential configuration were backed up under `~/.docker/` before repair.
- PostgreSQL's application database is `news`; the disposable integration-test database is `news_test`. The host connection port is 55432. Redis uses localhost:6379.
- API, PostgreSQL, and Redis are running. API docs: http://localhost:8000/docs. Temporary test scheduler/worker containers were removed; regular background ingestion has not been enabled.

## Verified outcome

All 46 tests pass, including real PostgreSQL migration/schema/vector/locking checks. Ruff checks pass. GitHub Actions passed the same application checks plus a production image build and non-root user check. A real scheduled ingestion stored 34 articles with 384-dimensional embeddings and 34 cluster memberships. It reported `partial` because ArXiv returned HTTP 429; the other sources completed. The small smoke run disabled HTML enrichment and limited each source to ten items. Full evidence is in [VALIDATION.md](VALIDATION.md) and [live-run.json](live-run.json).

Start the local environment from the project root:

```bash
colima start --profile ai-news --vm-type qemu
docker context use colima-ai-news
docker compose build api
docker compose up -d postgres redis api
```

Run the full suite from `backend/`:

```bash
TEST_DATABASE_URL=postgresql+psycopg://news:news@127.0.0.1:55432/news_test ../.venv/bin/pytest -q
../.venv/bin/ruff check app tests migrations
../.venv/bin/ruff format --check app tests migrations
```

See [VALIDATION.md](VALIDATION.md) for measured results and [SOURCES.md](SOURCES.md) for source coverage. `docker compose down` stops the project while retaining its data and model volumes.

## Next implementation boundary

1. Resolve the remaining ArXiv timeouts/rate limiting and verify feeds/adapters for Anthropic, Meta AI, Mistral, and Cohere. Complete an all-source successful run before enabling regular `worker` and `beat` services.
2. Define an authoritative publisher-correction policy that distinguishes corrected text from shorter feed excerpts. Currently, title changes and equal-length/shorter body corrections can remain stale.
3. Implement Week 3 shared cluster intelligence: deterministic input hashes; cached summary and structured analysis; model/prompt versions and token/cost records; ranking based on provenance, engagement, and recency. Select the provider/models and configure its credentials before real paid calls. Keep user personalization at delivery time.
4. Evaluate clustering against labeled events before changing the threshold or adopting HDBSCAN.
5. Implement Week 4 identity, preferences, dashboard, local-time digests, email delivery, and subscriptions.

No summaries or analysis are fabricated in the current milestone: those fields remain null. There is no customer-facing frontend or public deployment yet.
