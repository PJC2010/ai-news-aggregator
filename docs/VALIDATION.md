# Implementation validation

Checked on 2026-09-13. The original cloud checks used Python 3.12.14; the local follow-up uses Python 3.12.13 on macOS with PostgreSQL 16/pgvector and Redis running in Colima.

Current local suite: **46 passed, no skips, 2 dependency deprecation warnings**, including the PostgreSQL integration test. Ruff lint, formatting, and Compose configuration checks pass. The original cloud suite had 33 passing tests and skipped PostgreSQL.

## Completed checks

- Ruff lint and formatting checks.
- Application tests for canonical URLs, meaningful query parameters, ArXiv version normalization, SimHash behavior, feed parsing, UTC timestamps, conditional RSS requests, ArXiv category queries, HN filtering, source signal preservation, private-address rejection, redirect checks, bounded responses, retry cooldowns, robots policies, and trafilatura extraction.
- Database-backed application tests using in-memory SQLite: repeated ingestion, duplicate provenance, representative switching, event windows, source failures, embedding failure recovery, updated-body re-embedding, URL aliases, invalid article isolation, and seed idempotence.
- API checks: health, operator credential requirement, missing configuration, pagination limits, literal topic filtering, missing clusters, and static `/clusters/today` route ordering.
- Real MiniLM model download and execution on CPU: all vectors had 384 finite dimensions. A synthetic same-event paraphrase pair scored 0.9596 cosine similarity; an unrelated satellite-imagery item scored 0.0612. These three examples are a smoke check, not an evaluation of real-world clustering quality.
- Alembic PostgreSQL migration rendered successfully to SQL. SQL includes pgvector, a 384-dimensional embedding column, the HNSW index, provenance tables, and a partial unique primary-membership index.
- The migration now executes successfully on a real PostgreSQL 16/pgvector container. Alembic schema comparison, 384-dimensional vector persistence, primary membership, and advisory-lock acquisition/exclusion/release pass against the disposable `news_test` database.
- Added regression coverage and fixes for compressed HTTP responses being decoded twice and SimHash matching articles outside the seven-day window when newer coverage arrived first. Gzip/deflate decoding retains feed validators and enforces the decompressed response size limit; deduplication boundaries pass in both arrival orders.
- PostgreSQL and Redis Compose services start and report healthy. This Mac already runs a PostgreSQL server on 5432; the project's ignored `.env` uses 55432 via the new optional `POSTGRES_PORT` setting.
- The shared backend Docker image builds successfully. Migration and source-seeding containers exit successfully, the API reports ready at `http://localhost:8000/health/ready`, and its process runs as UID 10001. The build fixes a collision with Debian's existing `news` account and reuses one image across all Python services.
- Real MiniLM warmup succeeds inside the Docker image, using the shared model volume and the pinned revision; the output contains 384 dimensions.
- GitHub Actions passed for the [initial upload](https://github.com/PJC2010/ai-news-aggregator/actions/runs/34779633735) and the [container fixes](https://github.com/PJC2010/ai-news-aggregator/actions/runs/34779880549). The latter also builds the production image and verifies its non-root application user.
- Local protected source checks now pass for Hacker News and all ten RSS feeds. ArXiv still times out. The HN probe checks only two top stories and returned no matching AI items in that sample. Detailed results are in `SOURCES.md` and `local-source-check.json`.
- A real Celery Beat schedule dispatched one task through Redis to a Celery worker. With `SOURCE_LIMIT=10` and HTML enrichment disabled for the smoke run, it fetched 101 candidates, filtered 67, and stored/embedded/clustered 34 articles into 34 distinct clusters in about 49 seconds. The run correctly reported `partial`: ArXiv returned HTTP 429, while other sources completed. No articles were deduplicated in this small sample; deduplication and multi-article clustering remain covered by controlled tests. See [live-run.json](live-run.json).
- After ingestion, authenticated cluster/source/run endpoints returned successfully, unauthenticated cluster access returned HTTP 401, and API readiness passed. The database contains 34 articles, 34 embeddings, 34 memberships, and 34 observations. Temporary scheduler/worker containers were stopped and removed after the one scheduled run. API, PostgreSQL, and Redis remain available locally.

## Not yet verified

- An all-source successful live run remains pending: local ArXiv probes time out, and the container ingestion receives HTTP 429. The original cloud runtime also restricted direct source DNS; local protected fetching otherwise works.
- The live smoke run did not exercise HTML enrichment, the default 100-item source limit, long-running scheduling, or outage recovery under production load. The one-off 60-second scheduler test does not change the configured 30-minute default interval.
- Semantic clustering quality, recall during source outages, real workload performance, and source authority calibration need a labeled sample and live traffic.
- Same-publisher title corrections and equal-length/shorter body corrections are not yet propagated reliably. An update policy must distinguish publisher corrections from short feed excerpts before replacing previously extracted full text.

The current dependency set emits two deprecation warnings from the FastAPI/Starlette test-client stack. They do not fail the tests; they should be resolved during a future dependency upgrade.

No paid API calls, customer accounts, email sends, billing actions, or public deployments were performed.
