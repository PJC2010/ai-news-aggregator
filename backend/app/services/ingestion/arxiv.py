from datetime import UTC, datetime, timedelta

import feedparser

from app.services.ingestion.rss import entry_date
from app.services.ingestion.types import Candidate, FetchResult

CATEGORIES = ("cs.AI", "cs.LG", "cs.CL", "cs.CV")


async def fetch_arxiv(client, source, limit: int, lookback_days: int) -> FetchResult:
    # This is a rolling, bounded news snapshot, not an archive/backfill crawler.
    since = datetime.now(UTC) - timedelta(days=lookback_days)
    categories = " OR ".join(f"cat:{category}" for category in CATEGORIES)
    query = f"({categories}) AND submittedDate:[{since:%Y%m%d%H%M} TO 999912312359]"
    items = []
    for start in range(0, limit, 100):
        count = min(100, limit - start)
        response = await client.get(
            source.url,
            delay=3.1,
            params={
                "search_query": query,
                "start": start,
                "max_results": count,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            },
        )
        feed = feedparser.parse(response.content)
        if not feed.version or feed.bozo:
            raise ValueError("Invalid ArXiv Atom response")
        for entry in feed.entries:
            if entry.get("id", "").endswith("/api/errors"):
                raise ValueError("ArXiv returned an API error entry")
            if not entry.get("id") or not entry.get("title"):
                continue
            items.append(
                Candidate(
                    url=entry.id,
                    external_id=entry.id,
                    title=" ".join(entry.title.split()),
                    body=" ".join(entry.get("summary", "").split()),
                    author=", ".join(author.name for author in entry.get("authors", [])),
                    published_at=entry_date(entry),
                    metadata={
                        "categories": [tag.term for tag in entry.get("tags", [])],
                        "arxiv_id": entry.id,
                        "content_kind": "abstract",
                    },
                )
            )
        if len(feed.entries) < count:
            break
    return FetchResult(items)
