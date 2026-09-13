# Initial source registry

Configuration lives in `backend/app/sources.json`. `ai-news seed` inserts missing source URLs without overwriting an operator's current configuration or activation state. A new feed can be added to that file and seeded; existing source records are edited in PostgreSQL during this milestone.

The registry contains two API sources and eleven company-blog feeds. The first implementation uses feeds with known first-party endpoints; it does not yet cover every named company in the specification.

## Local application checks on 2026-09-13

Local macOS checks used the application's protected `FetchClient`, with direct connections and public-address validation. The [recorded results](local-source-check.json) show:

- All ten RSS feeds returned two parsed items each. AWS Machine Learning now responds successfully locally.
- Hacker News returned successfully with zero AI matches among the first two top stories checked. This small sample does not measure overall AI coverage.
- ArXiv returned `ReadTimeout`. Separate basic API queries to both `export.arxiv.org` and `arxiv.org` also timed out locally.

The subsequent scheduled Docker ingestion received HTTP 429 from ArXiv. Other sources completed, and the pipeline preserved their articles while marking the run `partial`; see [live-run.json](live-run.json).

The checks exposed a double-decompression bug in compressed HTTP responses. Normalizing headers after decoding fixed six RSS failures: OpenAI, Hugging Face, Databricks, GitHub AI & ML, Cloudflare AI, and Google AI. Regression tests cover gzip, deflate, response metadata, and decoded-size limits.

These results cover source fetching and parsing. See [validation results](VALIDATION.md) for database and full-pipeline checks.

## Source reliability follow-up on 2026-09-13

The [follow-up probe record](source-check-followup.json) records direct, bounded application fetches. ArXiv's official combined RSS endpoint, `https://rss.arxiv.org/rss/cs.AI+cs.LG+cs.CL+cs.CV`, returned HTTP 200 and valid RSS 2.0 with zero entries on Sunday, September 13. An empty weekend feed is expected: the [official RSS specification](https://info.arxiv.org/help/rss_specifications.html) documents empty feeds on weekends and some holidays. This confirms the endpoint works, not that it supplied papers during this check.

The ArXiv adapter now uses this RSS endpoint after an API timeout, HTTP 429, or HTTP 5xx. It records `fetch_mode: rss_fallback`, adds a warning, and labels the coverage limit in source state. API success records `fetch_mode: api`. Invalid API XML, API error entries, and other HTTP 4xx errors still fail without switching feeds. If the fallback fails or returns malformed XML, the source fails honestly. A long `Retry-After` delays recovery until a later scheduled run; shorter cooldowns are honored before RSS access.

RSS is the latest announcement snapshot, not a replacement for the API's complete requested lookback window. It can contain revisions and cross-listings. The adapter keeps categories, authors, announcement timestamps and type when present, retains the feed GUID, and canonicalizes paper URLs for existing deduplication. It filters dates outside the requested lookback and bounds returned items. [ArXiv documents the combined-category URL format](https://info.arxiv.org/help/rss.html) and an [aggregate limit of one request every three seconds](https://info.arxiv.org/help/api/tou.html); the fallback maintains a 3.1-second transition interval and uses the same protected `FetchClient` as existing feed adapters.

The initial RSS probe accidentally applied the HTML extraction guard, which rejects a missing robots file. A follow-up request confirmed `https://rss.arxiv.org/robots.txt` returns HTTP 404, then verified the explicitly published feed under [RFC 9309's unavailable-robots rule](https://www.rfc-editor.org/rfc/rfc9309.html#section-2.3.1.3). No proxy, private-address bypass, alternate identity, or change to the HTML extraction guard was used.

The company checks found:

| Publisher | First-party evidence | Result |
| --- | --- | --- |
| Mistral | Its news page advertises `https://mistral.ai/news/rss` with `rel=alternate` and RSS media type | HTTP 200; valid RSS 2.0 with 86 entries; usable first-party feed |
| Anthropic | Newsroom HTML has no advertised RSS/Atom link; `/news/rss.xml` was checked | Candidate URL returned HTTP 404; no usable feed verified |
| Meta AI | Blog HTML has no advertised RSS/Atom link; `/blog/rss/` was checked | Candidate URL returned HTTP 404; no usable feed verified |
| Cohere | Blog HTML has no advertised RSS/Atom link; `/blog/rss.xml` was checked | Candidate redirected to the HTML blog page, not a feed |

These bounded checks do not establish that Anthropic, Meta AI, or Cohere have no feeds. Their coverage remains unresolved; no unverified endpoint or new scraper was added. Mistral's verified feed is now in the registry. The subsequent Docker ingestion completed all eleven company feeds and HN; ArXiv used its empty Sunday RSS snapshot and kept the explicit partial-coverage warning. The run added five articles, bringing the stored total to 39. See [the live follow-up record](analysis-live-check.json).

## Historical cloud probe on 2026-09-13

The original cloud workspace could not resolve external domains through direct DNS. A separate read-only probe using its outbound proxy checked the registry endpoints. The [original probe record](source-probe.json) and results below are preserved as historical upstream-response evidence.

| Source | Endpoint | Probe result |
| --- | --- | --- |
| ArXiv AI/ML | https://export.arxiv.org/api/query | Timed out; adapter tested with Atom fixture |
| Hacker News | https://hacker-news.firebaseio.com/v0 | HTTP 200; 500 top-story IDs |
| OpenAI | https://openai.com/news/rss.xml | HTTP 200; RSS 2.0, 1,192 entries |
| Google DeepMind | https://deepmind.google/blog/rss.xml | HTTP 200; RSS 2.0, 100 entries |
| Google Research | https://research.google/blog/rss/ | HTTP 200; RSS 2.0, 100 entries |
| Hugging Face | https://huggingface.co/blog/feed.xml | HTTP 200; RSS 2.0, 861 entries |
| Microsoft Research | https://www.microsoft.com/en-us/research/feed/ | HTTP 200; RSS 2.0, 10 entries |
| AWS Machine Learning | https://aws.amazon.com/blogs/machine-learning/feed/ | Timed out in the cloud probe |
| Databricks | https://www.databricks.com/feed | HTTP 200; RSS 2.0, 10 entries; AI keyword filter enabled |
| GitHub AI & ML | https://github.blog/ai-and-ml/feed/ | HTTP 200; RSS 2.0, 10 entries |
| Cloudflare AI | https://blog.cloudflare.com/tag/ai/rss/ | HTTP 200; RSS 2.0, 20 entries |
| Google AI | https://blog.google/technology/ai/rss/ | HTTP 200; RSS 2.0, 20 entries |

Feed counts are observed response sizes, not article totals ingested. News publication dates, feed caps, and the rolling lookback reduce the records accepted by the application.

## Coverage gaps to resolve

Anthropic, Meta AI, Mistral, and Cohere were missing from the initial registry despite being named P0 companies in the spec. Mistral's first-party RSS endpoint is now verified above. Anthropic, Meta AI, and Cohere still need verified first-party feeds or reviewed adapters. This is a recorded coverage gap, not a claim that these publishers lack feeds.

Hacker News scans top stories rather than an exhaustive feed, and its AI relevance filter is a transparent keyword heuristic. ArXiv uses submitted date for a bounded rolling snapshot, so revisions to older papers are not an exhaustive update stream. Feeds without dates use fetch time for event placement; relative links are resolved against the feed URL.

The GitHub entry is its editorial AI/ML blog feed. It is not the deferred GitHub Trending feature.
