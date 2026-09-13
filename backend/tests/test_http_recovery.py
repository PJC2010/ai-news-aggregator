import gzip
import zlib
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from app.services.ingestion.http import FetchClient
from app.services.ingestion.parsing import ArticleParser


async def allow_fixture(_):
    pass


@pytest.mark.parametrize("encoding,compress", [("gzip", gzip.compress), ("deflate", zlib.compress)])
async def test_compressed_response_decodes_once_and_preserves_metadata(
    settings, encoding, compress
):
    payload = "<rss><title>AI research — new results</title></rss>".encode()
    compressed = compress(payload)
    settings.http_max_bytes = len(payload)

    def handle(request):
        return httpx.Response(
            203,
            headers={
                "Content-Encoding": encoding,
                "Content-Length": str(len(compressed)),
                "Content-Type": "application/rss+xml; charset=utf-8",
                "ETag": '"feed-v1"',
                "Last-Modified": "Sun, 13 Sep 2026 10:00:00 GMT",
            },
            stream=httpx.ByteStream(compressed),
        )

    async with FetchClient(settings, httpx.MockTransport(handle), allow_fixture) as client:
        response = await client.get("https://example.com/feed")
    assert response.content == payload
    assert response.text == payload.decode()
    assert response.status_code == 203
    assert str(response.url) == "https://example.com/feed"
    assert response.headers["content-type"] == "application/rss+xml; charset=utf-8"
    assert response.headers["etag"] == '"feed-v1"'
    assert response.headers["last-modified"] == "Sun, 13 Sep 2026 10:00:00 GMT"
    assert "content-encoding" not in response.headers
    assert response.headers["content-length"] == str(len(payload))


@pytest.mark.parametrize("encoding,compress", [("gzip", gzip.compress), ("deflate", zlib.compress)])
async def test_compressed_response_limit_applies_to_decoded_bytes(settings, encoding, compress):
    payload = b"<rss>" + b"Repeated feed entry " * 1000 + b"</rss>"
    compressed = compress(payload)
    settings.http_max_bytes = 256
    assert len(compressed) < settings.http_max_bytes < len(payload)

    def handle(request):
        return httpx.Response(
            200,
            headers={"Content-Encoding": encoding, "Content-Length": str(len(compressed))},
            stream=httpx.ByteStream(compressed),
        )

    async with FetchClient(settings, httpx.MockTransport(handle), allow_fixture) as client:
        with pytest.raises(ValueError, match="Response exceeds configured byte limit"):
            await client.get("https://example.com/feed")


async def test_retry_recovers_from_rate_limit(settings, monkeypatch):
    visited = []
    delays = []

    async def record_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr("app.services.ingestion.http.asyncio.sleep", record_sleep)

    def handle(request):
        visited.append(request)
        if len(visited) == 1:
            return httpx.Response(429, headers={"Retry-After": "4"})
        return httpx.Response(200, text="ok")

    async with FetchClient(settings, httpx.MockTransport(handle), allow_fixture) as client:
        assert (await client.get("https://example.com/feed")).text == "ok"
    assert len(visited) == 2 and 4 in delays


async def test_long_retry_after_date_is_not_ignored(settings):
    visited = []

    def handle(request):
        visited.append(request)
        return httpx.Response(
            429,
            headers={
                "Retry-After": format_datetime(
                    datetime.now(UTC) + timedelta(minutes=10), usegmt=True
                )
            },
        )

    async with FetchClient(settings, httpx.MockTransport(handle), allow_fixture) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.get("https://example.com/feed")
    assert len(visited) == 1


async def test_article_redirect_obeys_destination_robots(settings):
    visited = []

    def handle(request):
        visited.append(str(request.url))
        if request.url.path == "/robots.txt":
            policy = "Disallow: /" if request.url.host == "blocked.example" else "Allow: /"
            return httpx.Response(200, text=f"User-agent: *\n{policy}")
        return httpx.Response(302, headers={"location": "https://blocked.example/article"})

    async with FetchClient(settings, httpx.MockTransport(handle), allow_fixture) as client:
        assert await ArticleParser(client).extract("https://allowed.example/article") == ""
    assert "https://blocked.example/robots.txt" in visited
    assert "https://blocked.example/article" not in visited


async def test_article_body_extraction(settings):
    body = "Researchers released a language model with open weights and reproducible evaluation. "
    html = "<html><body><nav>Navigation</nav><article><h1>Model release</h1>"
    html += "".join(f"<p>{body * 5}</p>" for _ in range(8))
    html += "</article><footer>Footer</footer></body></html>"

    def handle(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    async with FetchClient(settings, httpx.MockTransport(handle), allow_fixture) as client:
        result = await ArticleParser(client).extract("https://example.com/release")
    assert "open weights" in result
    assert "Navigation" not in result
