import calendar
from datetime import UTC, datetime
from urllib.parse import urljoin

import feedparser

from app.services.ingestion.parsing import plain_text
from app.services.ingestion.types import Candidate, FetchResult


def entry_date(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(calendar.timegm(parsed), UTC) if parsed else None


def parse_feed(payload: bytes, base_url: str, limit: int) -> list[Candidate]:
    feed = feedparser.parse(payload)
    if not feed.version:
        raise ValueError("Response is not an RSS or Atom feed")
    # Reject partial/malformed XML instead of committing conditional-fetch state.
    if feed.bozo and "SAX" in type(feed.bozo_exception).__name__:
        raise ValueError("Malformed feed XML")
    items = []
    for entry in feed.entries[:limit]:
        title = plain_text(entry.get("title", ""))
        link = entry.get("link", "")
        if not title or not link:
            continue
        body = " ".join(c.get("value", "") for c in entry.get("content", []))
        body = plain_text(body or entry.get("summary", ""))
        items.append(
            Candidate(
                url=urljoin(base_url, link),
                title=title,
                body=body,
                body_kind="feed_full" if entry.get("content") else "feed_summary",
                author=entry.get("author"),
                published_at=entry_date(entry),
                external_id=str(entry.get("id") or urljoin(base_url, link)),
                metadata={"tags": [t.get("term") for t in entry.get("tags", [])]},
            )
        )
    return items


async def fetch_rss(client, source, limit: int) -> FetchResult:
    headers = {}
    if source.config.get("etag"):
        headers["If-None-Match"] = source.config["etag"]
    if source.config.get("last_modified"):
        headers["If-Modified-Since"] = source.config["last_modified"]
    response = await client.get(source.url, headers=headers)
    if response.status_code == 304:
        return FetchResult([])
    items = parse_feed(response.content, str(response.url), limit)
    return FetchResult(
        items,
        state={
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
        },
    )
