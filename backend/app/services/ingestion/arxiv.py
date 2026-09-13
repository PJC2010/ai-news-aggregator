import asyncio
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import feedparser
import httpx

from app.services.ingestion.parsing import plain_text
from app.services.ingestion.rss import entry_date
from app.services.ingestion.types import Candidate, FetchResult
from app.services.processing.dedup import canonicalize_url

CATEGORIES = ("cs.AI", "cs.LG", "cs.CL", "cs.CV")
RSS_URL = "https://rss.arxiv.org/rss/" + "+".join(CATEGORIES)
RSS_SCOPE_NOTE = (
    "ArXiv RSS contains only the latest announcement snapshot, including revisions and "
    "cross-listings; it does not cover the complete requested lookback. "
    "The feed can be empty on weekends and holidays."
)


async def fetch_arxiv(client, source, limit: int, lookback_days: int) -> FetchResult:
    try:
        return await _fetch_api(client, source, limit, lookback_days)
    except httpx.TimeoutException:
        failure = "API timeout"
        cooldown = 3.1
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status != 429 and not 500 <= status < 600:
            raise
        failure = f"API HTTP {status}"
        cooldown = _cooldown(exc.response.headers.get("retry-after", ""))
        if cooldown > 60:
            raise  # Preserve a long upstream cooldown for the next scheduled run.
    # arXiv's limit covers API and RSS together, including transitions between hosts.
    await asyncio.sleep(cooldown)
    response = await client.get(RSS_URL, delay=3.1)
    items = parse_arxiv_rss(response.content, limit, lookback_days)
    return FetchResult(
        items,
        state={"fetch_mode": "rss_fallback", "scope_note": RSS_SCOPE_NOTE},
        warnings=[f"{failure}; used RSS fallback. {RSS_SCOPE_NOTE}"],
    )


def _cooldown(retry_after: str) -> float:
    if retry_after.isdigit():
        return max(3.1, int(retry_after))
    if retry_after:
        try:
            target = parsedate_to_datetime(retry_after)
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
            return max(3.1, (target - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            pass
    return 3.1


def parse_arxiv_rss(payload: bytes, limit: int, lookback_days: int) -> list[Candidate]:
    feed = feedparser.parse(payload)
    if feed.version != "rss20" or feed.bozo:
        raise ValueError("Invalid ArXiv RSS response")
    since = datetime.now(UTC) - timedelta(days=lookback_days)
    items, seen = [], set()
    for entry in feed.entries:
        if len(items) >= limit:
            break
        title, link = plain_text(entry.get("title", "")), entry.get("link", "")
        if not title or not link:
            continue
        url = canonicalize_url(link)
        parts = urlsplit(url)
        if parts.hostname != "arxiv.org" or not re.fullmatch(
            r"/abs/(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})", parts.path
        ):
            raise ValueError("ArXiv RSS item has an invalid paper link")
        if url in seen:
            continue
        published_at = entry_date(entry)
        if published_at and published_at < since:
            continue
        body = plain_text(entry.get("summary", ""))
        body = re.sub(
            r"^arXiv:\S+\s+Announce Type:\s*\S+\s+Abstract:\s*",
            "",
            body,
            flags=re.IGNORECASE,
        )
        items.append(
            Candidate(
                url=url,
                external_id=url,
                title=title,
                body=body,
                body_kind="abstract",
                author=entry.get("author"),
                published_at=published_at,
                metadata={
                    "categories": [tag.term for tag in entry.get("tags", [])],
                    "arxiv_id": url,
                    "rss_guid": entry.get("id"),
                    "announce_type": entry.get("arxiv_announce_type"),
                    "content_kind": "abstract",
                    "date_kind": "announcement",
                    "fetch_mode": "rss_fallback",
                },
            )
        )
        seen.add(url)
    return items


async def _fetch_api(client, source, limit: int, lookback_days: int) -> FetchResult:
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
        for entry in feed.entries[:count]:
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
                    body_kind="abstract",
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
    return FetchResult(
        items,
        state={
            "fetch_mode": "api",
            "scope_note": "Bounded snapshot filtered by submitted date within the lookback window.",
        },
    )
