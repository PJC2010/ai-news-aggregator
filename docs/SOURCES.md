# Initial source registry

Configuration lives in `backend/app/sources.json`. `ai-news seed` inserts missing source URLs without overwriting an operator's current configuration or activation state. A new feed can be added to that file and seeded; existing source records are edited in PostgreSQL during this milestone.

The registry contains two API sources and ten company-blog feeds. The first implementation uses feeds with known first-party endpoints; it does not yet cover every named company in the specification.

## Source checks on 2026-09-13

Application fetches could not resolve external domains with this workspace's direct DNS. A separate read-only probe using the runtime's configured outbound proxy checked the fixed registry endpoints. The results below describe those upstream responses, not a completed database ingestion run. The protected application fetcher was not weakened to make this environment pass.

| Source | Endpoint | Probe result |
| --- | --- | --- |
| ArXiv AI/ML | https://export.arxiv.org/api/query | Timed out; adapter tested with Atom fixture |
| Hacker News | https://hacker-news.firebaseio.com/v0 | HTTP 200; 500 top-story IDs |
| OpenAI | https://openai.com/news/rss.xml | HTTP 200; RSS 2.0, 1,192 entries |
| Google DeepMind | https://deepmind.google/blog/rss.xml | HTTP 200; RSS 2.0, 100 entries |
| Google Research | https://research.google/blog/rss/ | HTTP 200; RSS 2.0, 100 entries |
| Hugging Face | https://huggingface.co/blog/feed.xml | HTTP 200; RSS 2.0, 861 entries |
| Microsoft Research | https://www.microsoft.com/en-us/research/feed/ | HTTP 200; RSS 2.0, 10 entries |
| AWS Machine Learning | https://aws.amazon.com/blogs/machine-learning/feed/ | Timed out; recheck on the deployment host |
| Databricks | https://www.databricks.com/feed | HTTP 200; RSS 2.0, 10 entries; AI keyword filter enabled |
| GitHub AI & ML | https://github.blog/ai-and-ml/feed/ | HTTP 200; RSS 2.0, 10 entries |
| Cloudflare AI | https://blog.cloudflare.com/tag/ai/rss/ | HTTP 200; RSS 2.0, 20 entries |
| Google AI | https://blog.google/technology/ai/rss/ | HTTP 200; RSS 2.0, 20 entries |

Feed counts are observed response sizes, not article totals ingested. News publication dates, feed caps, and the rolling lookback reduce the records accepted by the application.

## Coverage gaps to resolve

Anthropic, Meta AI, Mistral, and Cohere are named P0 companies in the spec but are not configured in this first registry. Their official RSS/API endpoints have not been verified for this implementation. Add verified first-party feeds or explicitly reviewed fallback adapters in the next pipeline iteration. This is a recorded coverage gap, not a claim that these publishers lack feeds.

Hacker News scans top stories rather than an exhaustive feed, and its AI relevance filter is a transparent keyword heuristic. ArXiv uses submitted date for a bounded rolling snapshot, so revisions to older papers are not an exhaustive update stream. Feeds without dates use fetch time for event placement; relative links are resolved against the feed URL.

The GitHub entry is its editorial AI/ML blog feed. It is not the deferred GitHub Trending feature.
