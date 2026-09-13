import asyncio
import ipaddress
import socket
import time
from collections import defaultdict
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import Settings
from app.services.processing.dedup import canonicalize_url


async def validate_public_url(url: str) -> None:
    canonicalize_url(url)  # Validate URL syntax without changing the host being requested.
    parts = urlsplit(url)
    if parts.port not in {None, 80, 443}:
        raise ValueError("Only HTTP(S) default ports are allowed")
    addresses = await asyncio.get_running_loop().getaddrinfo(
        parts.hostname,
        parts.port or (443 if parts.scheme == "https" else 80),
        type=socket.SOCK_STREAM,
    )
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Fetching private or non-global addresses is prohibited")


class FetchClient:
    """Bounded public HTTP fetches, paced requests, retries, validated redirects."""

    def __init__(self, settings: Settings, transport=None, validator=validate_public_url):
        self.settings = settings
        self.validator = validator
        self.client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            transport=transport,
            headers={"User-Agent": settings.user_agent},
            follow_redirects=False,
            trust_env=False,
        )
        self.locks = defaultdict(asyncio.Lock)
        self.last_request = defaultdict(float)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.client.aclose()

    async def get(self, url: str, *, params=None, headers=None, delay: float = 0, authorize=None):
        if params:
            url = str(httpx.URL(url, params=params))
        for _redirect in range(6):
            await self.validator(url)
            policy_delay = await authorize(url) if authorize else 0
            host = urlsplit(url).hostname
            async with self.locks[host]:
                for attempt in range(3):
                    interval = max(delay, policy_delay, self.settings.per_host_delay_seconds)
                    if host in {"arxiv.org", "export.arxiv.org"}:
                        interval = max(interval, 3.1)
                    await asyncio.sleep(
                        max(0, interval - (time.monotonic() - self.last_request[host]))
                    )
                    self.last_request[host] = time.monotonic()
                    try:
                        async with self.client.stream("GET", url, headers=headers) as response:
                            if response.status_code in {429, 500, 502, 503, 504}:
                                response.raise_for_status()
                            content = bytearray()
                            async for chunk in response.aiter_bytes():
                                content.extend(chunk)
                                if len(content) > self.settings.http_max_bytes:
                                    raise ValueError("Response exceeds configured byte limit")
                            # aiter_bytes() has already decompressed the body. Preserve
                            # validators, but describe the decoded representation below.
                            decoded_headers = response.headers.copy()
                            for name in ("content-encoding", "content-length", "transfer-encoding"):
                                decoded_headers.pop(name, None)
                            result = httpx.Response(
                                response.status_code,
                                headers=decoded_headers,
                                content=bytes(content),
                                request=response.request,
                            )
                        break
                    except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                        if attempt == 2:
                            raise
                        retry_after = (
                            exc.response.headers.get("retry-after", "")
                            if isinstance(exc, httpx.HTTPStatusError)
                            else ""
                        )
                        wait = 0
                        if retry_after.isdigit():
                            wait = int(retry_after)
                        elif retry_after:
                            try:
                                wait = max(
                                    0,
                                    (
                                        parsedate_to_datetime(retry_after) - datetime.now(UTC)
                                    ).total_seconds(),
                                )
                            except (TypeError, ValueError):
                                pass
                        if wait > 60:
                            raise  # Let the next scheduled run retry; never ignore a long cooldown.
                        await asyncio.sleep(max(2**attempt, wait))
            if result.status_code in {301, 302, 303, 307, 308}:
                new_url = urljoin(url, result.headers["location"])
                if urlsplit(new_url).netloc != urlsplit(url).netloc:
                    headers = None
                url = new_url
                continue
            if result.status_code != 304:
                result.raise_for_status()
            return result
        raise ValueError("Too many redirects")
