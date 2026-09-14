# Implementation validation

## Dashboard checks — 2026-09-14

The dashboard change was checked separately on Linux with Python 3.12 and Node
24.19.0, starting from upstream commit `956845c`.

- Backend suite: **245 passed, 1 skipped**. The skipped test needs a real
  `TEST_DATABASE_URL`; Docker/PostgreSQL is not installed in this workspace.
- Backend Ruff lint and formatting checks passed. Alembic generated the full SQL
  through `0003_dashboard_users`; real migration execution is covered by the
  existing PostgreSQL/pgvector GitHub Actions job.
- Next.js production build and TypeScript checks passed. The locked frontend uses
  Next.js 16.3.5, React 19.3.0, and Supabase SSR 0.12.7.
- Three utility tests passed for safe external URLs, query normalization, and
  filter-preserving pagination.
- **10 browser scenarios passed** across desktop, mobile, missing Auth setup,
  invalid callbacks, and the real Next.js-to-FastAPI integration. Integration uses
  a test-only identity provider and isolated SQLite, not a real Supabase project.
  It verifies account identity despite a forged embedded session user, preference
  isolation, saved filters, and honest service-outage states. Demo requests stay
  disconnected from the backend.
- Desktop and mobile screenshots were visually checked for clipping and layout.
  See [desktop preview](screenshots/dashboard-desktop.png) and
  [mobile preview](screenshots/dashboard-mobile.png). Both contain illustrative
  demo content.

The standard Playwright browser download timed out in this workspace. Browser
checks used an npm-packaged Chromium 153 executable; CI installs Playwright's
standard Chromium. Live Supabase email/PKCE and production SMTP delivery still
need a configured project. No real accounts, email sends, paid model calls,
subscriptions, or deployments were created during this milestone.

## Earlier backend validation — 2026-09-13

Checked on 2026-09-13 using Python 3.12.13 on macOS, PostgreSQL 16/pgvector, Redis, and Docker in the Colima `ai-news` profile.

## Current checks

**219 tests passed, no skips, two dependency deprecation warnings.** Ruff lint and formatting pass. The production backend image builds, migrations and source seeding complete, and the API reports ready. Database checks exercise the real PostgreSQL schema, not only SQLite.

The suite covers:

- Canonical URLs, SimHash boundaries, RSS/Atom parsing, UTC timestamps, conditional feed requests, ArXiv queries and official RSS fallback, HN source signals, public-address checks, redirects, bounded/decompressed HTTP responses, retries, cooldowns, robots policies, and article extraction.
- Replay-safe ingestion, provenance, representative switching, event windows, source failures, embedding recovery, publisher title and shorter/equal-body corrections, preservation of full text against shorter excerpts, and migration-era text-kind recovery. Community text cannot be attributed to an official publisher through either arrival order.
- Strict provider response envelopes and output schemas, JSON request settings, model/request-ID storage bounds, secret redaction, error mapping, missing or inconsistent usage, truncation, and no automatic request retries.
- Two-pass analysis, durable journals committed before requests, versioned hashes and cached stages, model/prompt/evidence/token-limit invalidation, retained summary after second-pass failure, insufficient evidence, excerpt limits, evidence-grounded links, and interrupted-run recovery.
- Conservative spending reservations, pre-request budget enforcement, failed-output charges, unknown-usage timeout reservations, zero-call replays, and resuming a budget-limited event.
- Ranked global pagination, stable ties, freshness decay, neutral missing significance, independent source/category diversity, and unique HN story engagement. Pagination does not rank only the selected page.
- Operator authentication, credential/configuration states, pagination/filter validation, ranked/latest sorting, analysis history and cost totals, latest-20 audit entries, read-only status inspection, CLI argument/exit behavior, and writer-lock exclusion/release.
- Real PostgreSQL Alembic upgrade and schema comparison, 384-dimensional vector persistence, cluster membership, and advisory locking. Both migration revisions are applied locally; existing articles and clusters remain intact.

## Live source and ingestion checks

The original scheduled smoke run stored 34 articles and correctly reported ArXiv HTTP 429. Its record remains in [live-run.json](live-run.json). Earlier source probes and the resolved HTTP double-decompression defect are documented in [SOURCES.md](SOURCES.md).

The follow-up bounded run used `SOURCE_LIMIT=10`, disabled HTML enrichment, and kept automatic analysis off. It fetched 51 candidates, filtered 32, retained 14 duplicate observations, and added/embedded/clustered five new articles. The database now holds **39 articles, 39 embeddings, 39 cluster memberships, 39 source observations, and 13 sources**. RSS conditional responses explain why the candidate count is lower than the original run.

All eleven company feeds and HN completed. ArXiv's API returned HTTP 429 and its official RSS fallback succeeded with an empty Sunday announcement snapshot. The pipeline correctly remains `partial` because RSS does not recover the full requested lookback. `fetch_mode`, a coverage explanation, and the warning remain inspectable. This is not an all-source full-coverage success. Mistral is now registered; Anthropic, Meta AI, and Cohere remain coverage gaps.

## Live analysis checks

The configured DeepSeek key authenticated successfully; the account exposed `deepseek-flash` and `deepseek-v4-pro`. One real AWS event completed both paid stages under a temporary USD 0.05 run limit. The first pass used 2,003 input and 165 output tokens; the second used 2,611 input and 170 output tokens. The estimated charge at the recorded peak rates was **USD 0.00491862**. A replay of the same event used the completed cache and made no new model calls, with zero incremental estimated cost. Two earlier headline-only events were marked `insufficient_evidence`.

Review of the first generated output exposed a tutorial classified as a tool release and an unstated article excerpt boundary. The final implementation explicitly labels truncated evidence and uses `analysis-v2` to distinguish tutorials from new releases. The final live run classified this walkthrough as `other`, explicitly qualified the excerpt in its summary, and completed both stages for an estimated USD 0.004782312. Its replay again made no new calls. **Four paid requests across both live checks totaled an estimated USD 0.009700932**, under one cent. Final deployment verification is recorded in [analysis-live-check.json](analysis-live-check.json). Costs are versioned estimates derived from usage, not provider invoices; off-peak/provider caching discounts may make actual billing lower.

API, PostgreSQL, and Redis remain running on localhost. Regular worker and beat services remain stopped. `ANALYSIS_ENABLED` defaults to false, so ongoing automatic paid generation has not been enabled.

## Earlier infrastructure checks

- MiniLM downloaded and ran on CPU with 384 finite dimensions. A synthetic same-event pair scored 0.9596 cosine similarity, compared with 0.0612 for an unrelated pair. These were smoke examples, not clustering-quality evaluation.
- Fixed Debian's existing `news` account collision with the non-root `ainews` user at UID 10001. All Python services share one backend image. PostgreSQL's host port is configurable; this Mac uses 55432.
- A real Celery Beat task dispatched through Redis to a worker and completed ingestion. Temporary scheduler/worker containers were removed afterward.
- GitHub Actions passed for the [initial upload](https://github.com/PJC2010/ai-news-aggregator/actions/runs/34779633735) and [container fixes](https://github.com/PJC2010/ai-news-aggregator/actions/runs/34779880549), including production image and non-root runtime checks.

## Limits of this validation

Generated text was reviewed on one event; editorial accuracy, classification quality, and ranking usefulness need a labeled evaluation set. The clustering threshold remains unchanged, and HDBSCAN is not implemented. A bounded RSS snapshot does not measure comprehensive source recall or outage recovery. The live ingestion did not exercise HTML enrichment, the default 100-item limit, or sustained production load. Ranking computes over a filtered set in memory and needs a scalable serving strategy before broad deployment.

Two FastAPI/Starlette test-client deprecation warnings remain; they do not fail the suite. No customer accounts, email sends, subscription purchases, or public deployments were performed.
