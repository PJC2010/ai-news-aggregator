import hashlib
import re
from collections import Counter
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid"}


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("Expected an absolute HTTP(S) URL")
    if parts.username or parts.password:
        raise ValueError("Credentials in URLs are not supported")
    host = parts.hostname.lower().encode("idna").decode("ascii")
    scheme = parts.scheme.lower()
    port = parts.port
    host = f"[{host}]" if ":" in host else host
    if port and (scheme, port) not in {("http", 80), ("https", 443)}:
        host += f":{port}"
    path = parts.path or "/"
    if host in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
        host, scheme = "arxiv.org", "https"
        path = re.sub(r"^/pdf/", "/abs/", path)
        path = re.sub(r"\.pdf$", "", path)
        path = re.sub(r"v\d+$", "", path)
    # Preserve meaningful parameters (e.g. HN item?id=...) and trailing slashes.
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING
    ]
    return urlunsplit((scheme, host, path, urlencode(sorted(query)), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(canonicalize_url(url).encode()).hexdigest()


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def simhash(text: str, min_words: int = 80) -> str | None:
    tokens = words(text)
    if len(tokens) < min_words:
        return None  # Headlines/short excerpts are not reliable near-duplicate evidence.
    features = Counter(" ".join(tokens[i : i + 3]) for i in range(len(tokens) - 2))
    votes = [0] * 64
    for feature, frequency in features.items():
        bits = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "big")
        for bit in range(64):
            votes[bit] += frequency if bits & (1 << bit) else -frequency
    return f"{sum(1 << i for i, vote in enumerate(votes) if vote > 0):016x}"


def hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()
