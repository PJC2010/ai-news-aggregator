import pytest

from app.services.processing.dedup import canonicalize_url, hamming_distance, simhash, url_hash


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (
            "HTTPS://Example.com:443/path?utm_source=hn&b=2&a=1#section",
            "https://example.com/path?a=1&b=2",
        ),
        ("http://arxiv.org/pdf/2609.12345v2.pdf", "https://arxiv.org/abs/2609.12345"),
    ],
)
def test_url_duplicates(left, right):
    assert canonicalize_url(left) == right
    assert url_hash(left) == url_hash(right)


def test_meaningful_url_differences_survive():
    assert url_hash("https://news.ycombinator.com/item?id=1") != url_hash(
        "https://news.ycombinator.com/item?id=2"
    )
    assert canonicalize_url("https://example.com/path/").endswith("/path/")


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "javascript:alert(1)", "https://user:secret@example.com", "/relative"],
)
def test_invalid_urls(url):
    with pytest.raises(ValueError):
        canonicalize_url(url)


def test_simhash_is_deterministic_and_conservative():
    text = " ".join(f"token{i}" for i in range(500))
    assert simhash("A short headline") is None
    assert simhash(text) == simhash(text.upper())
    assert hamming_distance(simhash(text), simhash(text.replace("token123", "changed"))) <= 3
    assert (
        hamming_distance(simhash(text), simhash(" ".join(f"different{i}" for i in range(500)))) > 3
    )
