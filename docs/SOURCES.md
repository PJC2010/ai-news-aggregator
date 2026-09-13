# Initial source registry

Configuration lives in `backend/app/sources.json`. `ai-news seed` inserts missing source URLs without overwriting an operator's current configuration or activation state. A new feed can be added to that file and seeded; existing source records are edited in PostgreSQL during this milestone.

The registry contains two API sources and ten company-blog feeds. The first implementation uses feeds with known first-party endpoints; it does not yet cover every named company in the specification.

## Local application checks on 2026-09-13

Local macOS checks used the application's protected `FetchClient`, with direct connections and public-address validation. The [recorded results](local-source-check.json) show:

- All ten RSS feeds returned two parsed items each. AWS Machine Learning now responds successfully locally.
- Hacker News returned successfully with zero AI matches among the first two top stories checked. This small sample does not measure overall AI coverage.
- ArXiv returned `ReadTimeout`. Separate basic API queries to both `export.arxiv.org` and `arxiv.org` also timed out locally.

The subsequent scheduled Docker ingestion received HTTP 429 from ArXiv. Other sources completed, and the pipeline preserved their articles while marking the run `partial`; see [live-run.json](live-run.json).

The checks exposed a double-decompression bug in compressed HTTP responses. Normalizing headers after decoding fixed six RSS failures: OpenAI, Hugging Face, Databricks, GitHub AI & ML, Cloudflare AI, and Google AI. Regression tests cover gzip, deflate, response metadata, and decoded-size limits.

These results cover source fetching and parsing. See [validation results](VALIDATION.md) for database and full-pipeline checks.

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

Anthropic, Meta AI, Mistral, and Cohere are named P0 companies in the spec but are not configured in this first registry. Their official RSS/API endpoints have not been verified for this implementation. Add verified first-party feeds or explicitly reviewed fallback adapters in the next pipeline iteration. This is a recorded coverage gap, not a claim that these publishers lack feeds.

Hacker News scans top stories rather than an exhaustive feed, and its AI relevance filter is a transparent keyword heuristic. ArXiv uses submitted date for a bounded rolling snapshot, so revisions to older papers are not an exhaustive update stream. Feeds without dates use fetch time for event placement; relative links are resolved against the feed URL.

The GitHub entry is its editorial AI/ML blog feed. It is not the deferred GitHub Trending feature.
