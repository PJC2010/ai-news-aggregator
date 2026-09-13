from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services.ingestion.arxiv import RSS_URL, fetch_arxiv, parse_arxiv_rss
from app.services.ingestion.http import FetchClient
from app.services.processing.dedup import canonicalize_url

API_URL = "https://export.arxiv.org/api/query"
API_FIXTURE = (Path(__file__).parent / "fixtures" / "arxiv.xml").read_bytes()


def rss(*, link="https://arxiv.org/abs/2609.12345v2", published=None, repeat=1):
    published = published or datetime.now(UTC) - timedelta(hours=1)
    entry = f"""
    <item><title>A language model paper</title><link>{link}</link>
    <description>arXiv:2609.12345v2 Announce Type: replace
    Abstract: An abstract with reproducible evaluation.</description>
    <guid isPermaLink="false">oai:arXiv.org:2609.12345v2</guid>
    <category>cs.CL</category><category>cs.LG</category>
    <pubDate>{format_datetime(published)}</pubDate>
    <arxiv:announce_type>replace</arxiv:announce_type>
    <dc:creator>First Author, Second Author</dc:creator></item>
    """
    return (
        f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:arxiv="http://arxiv.org/schemas/atom">
    <channel><title>ArXiv fixture</title><link>{RSS_URL}</link>
    <description>Recent announcements</description>{entry * repeat}</channel></rss>"""
    ).encode()


@pytest.fixture
def delays(monkeypatch):
    recorded = []

    async def record(delay):
        recorded.append(delay)

    monkeypatch.setattr("app.services.ingestion.http.asyncio.sleep", record)
    return recorded


async def allow_fixture(_):
    pass


async def run_fetch(settings, handler):
    async with FetchClient(settings, httpx.MockTransport(handler), allow_fixture) as client:
        return await fetch_arxiv(client, SimpleNamespace(url=API_URL), 5, 7)


async def test_api_success_records_mode_and_does_not_call_rss(settings, delays):
    visited = []

    def handle(request):
        visited.append(request.url.host)
        return httpx.Response(200, content=API_FIXTURE)

    result = await run_fetch(settings, handle)
    assert result.state["fetch_mode"] == "api"
    assert result.warnings == []
    assert visited == ["export.arxiv.org"]
    assert canonicalize_url(result.items[0].url) == "https://arxiv.org/abs/2609.12345"


@pytest.mark.parametrize("failure", ["timeout", 429, 500, 503, 599])
async def test_transient_api_failure_uses_bounded_official_rss(settings, delays, failure):
    visited = []

    def handle(request):
        visited.append(request)
        if request.url.host == "export.arxiv.org":
            if failure == "timeout":
                raise httpx.ReadTimeout("timeout", request=request)
            return httpx.Response(failure)
        assert str(request.url) == RSS_URL
        return httpx.Response(200, content=rss(repeat=2))

    result = await run_fetch(settings, handle)
    assert result.state["fetch_mode"] == "rss_fallback"
    assert "complete requested lookback" in result.state["scope_note"]
    assert result.warnings and "fallback" in result.warnings[0]
    assert len(result.items) == 1
    item = result.items[0]
    assert item.url == item.external_id == "https://arxiv.org/abs/2609.12345"
    assert item.author == "First Author, Second Author"
    assert item.metadata["categories"] == ["cs.CL", "cs.LG"]
    assert item.metadata["rss_guid"] == "oai:arXiv.org:2609.12345v2"
    assert item.metadata["date_kind"] == "announcement"
    assert item.metadata["announce_type"] == "replace"
    assert item.published_at is not None
    assert item.body == "An abstract with reproducible evaluation."
    assert sum(request.url.host == "rss.arxiv.org" for request in visited) == 1
    assert 3.1 in delays


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_nontransient_api_failure_never_falls_back(settings, delays, status):
    visited = []

    def handle(request):
        visited.append(request.url.host)
        return httpx.Response(status)

    with pytest.raises(httpx.HTTPStatusError):
        await run_fetch(settings, handle)
    assert visited == ["export.arxiv.org"]


@pytest.mark.parametrize(
    "body",
    [
        b"<html>not an Atom feed</html>",
        b"<feed xmlns='http://www.w3.org/2005/Atom'><entry>",
        API_FIXTURE.replace(b"http://arxiv.org/abs/2609.12345v1", b"http://arxiv.org/api/errors"),
    ],
)
async def test_malformed_api_data_never_falls_back(settings, delays, body):
    visited = []

    def handle(request):
        visited.append(request.url.host)
        return httpx.Response(200, content=body)

    with pytest.raises(ValueError):
        await run_fetch(settings, handle)
    assert visited == ["export.arxiv.org"]


@pytest.mark.parametrize(
    "retry_after",
    [
        "600",
        format_datetime(datetime.now(UTC) + timedelta(hours=1), usegmt=True),
    ],
)
async def test_long_upstream_cooldown_prevents_rss_request(settings, delays, retry_after):
    visited = []

    def handle(request):
        visited.append(request.url.host)
        return httpx.Response(429, headers={"Retry-After": retry_after})

    with pytest.raises(httpx.HTTPStatusError):
        await run_fetch(settings, handle)
    assert visited == ["export.arxiv.org"]


async def test_short_upstream_cooldown_is_respected_before_rss(settings, delays):
    def handle(request):
        if request.url.host == "export.arxiv.org":
            return httpx.Response(429, headers={"Retry-After": "12"})
        return httpx.Response(200, content=rss())

    assert (await run_fetch(settings, handle)).state["fetch_mode"] == "rss_fallback"
    assert delays.count(12) == 3


@pytest.mark.parametrize("fallback", [403, 429, "timeout", "malformed"])
async def test_failed_rss_does_not_report_success(settings, delays, fallback):
    def handle(request):
        if request.url.host == "export.arxiv.org":
            return httpx.Response(503)
        if fallback == "timeout":
            raise httpx.ReadTimeout("RSS timeout", request=request)
        if fallback == "malformed":
            return httpx.Response(200, content=b"<rss version='2.0'><channel><item>")
        return httpx.Response(fallback)

    with pytest.raises((httpx.HTTPStatusError, httpx.TimeoutException, ValueError)):
        await run_fetch(settings, handle)


def test_rss_snapshot_accepts_empty_and_filters_dates_and_respects_limit():
    assert parse_arxiv_rss(rss(repeat=0), 5, 7) == []
    assert parse_arxiv_rss(rss(published=datetime.now(UTC) - timedelta(days=8)), 5, 7) == []
    assert parse_arxiv_rss(rss(), 0, 7) == []
    assert len(parse_arxiv_rss(rss(repeat=2), 1, 7)) == 1


@pytest.mark.parametrize(
    "link",
    [
        "https://unrelated.example/abs/2609.12345",
        "https://arxiv.org/help",
        "javascript:alert(1)",
    ],
)
def test_rss_rejects_unexpected_paper_links(link):
    with pytest.raises(ValueError):
        parse_arxiv_rss(rss(link=link), 5, 7)
