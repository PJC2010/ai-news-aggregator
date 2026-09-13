from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services.ingestion.arxiv import fetch_arxiv
from app.services.ingestion.hackernews import fetch_hackernews
from app.services.ingestion.http import FetchClient, validate_public_url
from app.services.ingestion.parsing import ArticleParser, plain_text
from app.services.ingestion.rss import fetch_rss, parse_feed

FIXTURES = Path(__file__).parent / "fixtures"


async def allow_fixture(_):
    pass


def test_rss_and_atom_parsing():
    items = parse_feed((FIXTURES / "feed.xml").read_bytes(), "https://lab.example/feed", 5)
    assert len(items) == 2
    assert items[0].title == "New language model & weights"
    assert items[0].body == "Weights are available for research ."
    assert items[0].published_at.utcoffset().total_seconds() == 0
    assert items[1].published_at is None
    assert items[1].url == "https://lab.example/note"
    assert plain_text("<script>bad()</script><p>Keep this</p>") == "Keep this"
    with pytest.raises(ValueError):
        parse_feed(b"<html>not a feed</html>", "https://example.com", 2)


async def test_conditional_rss(settings):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(304)

    source = SimpleNamespace(url="https://example.com/feed", config={"etag": '"v1"'})
    async with FetchClient(settings, httpx.MockTransport(handle), allow_fixture) as client:
        result = await fetch_rss(client, source, 5)
    assert result.items == []
    assert requests[0].headers["if-none-match"] == '"v1"'


async def test_arxiv_categories_and_abstract(settings, monkeypatch):
    requests = []

    async def no_wait(_):
        pass

    monkeypatch.setattr("app.services.ingestion.http.asyncio.sleep", no_wait)

    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=(FIXTURES / "arxiv.xml").read_bytes())

    async with FetchClient(settings, httpx.MockTransport(handle), allow_fixture) as client:
        result = await fetch_arxiv(
            client, SimpleNamespace(url="https://export.arxiv.org/api/query"), 5, 7
        )
    assert len(result.items) == 1
    assert result.items[0].metadata["categories"] == ["cs.CL", "cs.LG"]
    assert result.items[0].author == "Example Author"
    query = requests[0].url.params["search_query"]
    assert all(category in query for category in ["cs.AI", "cs.LG", "cs.CL", "cs.CV"])


async def test_hn_filters_and_preserves_signals(settings, monkeypatch):
    async def no_wait(_):
        pass

    monkeypatch.setattr("app.services.ingestion.http.asyncio.sleep", no_wait)

    def handle(request):
        if "topstories" in request.url.path:
            return httpx.Response(200, json=[1, 2, 3, 4, 5])
        item_id = int(request.url.path.split("/")[-1].split(".")[0])
        item = {
            "id": item_id,
            "type": "story",
            "title": "A new language model with AI",
            "time": 1789290000,
            "score": 99,
            "descendants": 17,
        }
        if item_id == 2:
            item["title"] = "A wooden chair"
        if item_id == 3:
            item["deleted"] = True
        if item_id == 4:
            item["type"] = "job"
        if item_id == 5:
            return httpx.Response(404)
        return httpx.Response(200, json=item)

    async with FetchClient(settings, httpx.MockTransport(handle), allow_fixture) as client:
        result = await fetch_hackernews(client, SimpleNamespace(url="https://hn.example/v0"), 5)
    assert len(result.items) == 1
    assert result.items[0].metadata["hn_points"] == 99
    assert result.items[0].url.endswith("item?id=1")
    assert len(result.warnings) == 1


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/"])
async def test_private_destinations_rejected(url):
    with pytest.raises(ValueError):
        await validate_public_url(url)


async def test_redirect_is_revalidated_and_large_response_rejected(settings):
    validated = []

    async def validator(url):
        validated.append(url)
        if "127.0.0.1" in url:
            raise ValueError("private redirect")

    def redirect(_):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

    async with FetchClient(settings, httpx.MockTransport(redirect), validator) as client:
        with pytest.raises(ValueError, match="private redirect"):
            await client.get("https://example.com")
    assert len(validated) == 2
    settings.http_max_bytes = 5
    async with FetchClient(
        settings, httpx.MockTransport(lambda _: httpx.Response(200, text="123456")), allow_fixture
    ) as client:
        with pytest.raises(ValueError, match="byte limit"):
            await client.get("https://example.com")


async def test_robots_disallow_preserves_feed_body(settings):
    visited = []

    def handle(request):
        visited.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow: /private")

    async with FetchClient(settings, httpx.MockTransport(handle), allow_fixture) as client:
        assert await ArticleParser(client).extract("https://example.com/private/article") == ""
    assert visited == ["/robots.txt"]
