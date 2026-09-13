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
- Upstream source probes: Hacker News and nine RSS feeds returned usable responses. ArXiv and AWS timed out. Full details are in `SOURCES.md`.

## Not yet verified

- Backend image build, API container startup, and full-stack verification are in progress during the local follow-up.
- A GitHub Actions workflow provisions pgvector and runs all tests; remote execution is pending the project upload.
- A complete live fetch → PostgreSQL → embedding → cluster run and Celery/Redis scheduling remain to be exercised on a Docker-capable host.
- The original cloud runtime restricted direct source DNS. Local direct fetches work, and source checks are being repeated after the compressed-response fix. Public-address checks remain enabled.
- Semantic clustering quality, recall during source outages, real workload performance, and source authority calibration need a labeled sample and live traffic.
- Same-publisher title corrections and equal-length/shorter body corrections are not yet propagated reliably. An update policy must distinguish publisher corrections from short feed excerpts before replacing previously extracted full text.

The current dependency set emits two deprecation warnings from the FastAPI/Starlette test-client stack. They do not fail the tests; they should be resolved during a future dependency upgrade.

No paid API calls, customer accounts, email sends, billing actions, or deployments were performed.
