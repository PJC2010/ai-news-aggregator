from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models import Article, Cluster, ClusterArticle, Observation, Source, utcnow
from app.seed import seed_sources
from app.services.ingestion.types import Candidate, FetchResult
from app.services.pipeline import run_pipeline, store_candidate
from app.services.processing.cluster import assign_cluster
from app.services.processing.embeddings import validate_vector


def make_source(name, authority=5):
    return Source(
        name=name,
        url=f"https://{name}.example/feed",
        type="rss",
        category="company",
        authority_score=authority,
        config={},
    )


async def test_pipeline_replay_and_provenance(factory, settings, embedder):
    with factory() as session:
        session.add_all([make_source("lab", 10), make_source("hn", 5), make_source("other", 7)])
        session.commit()

    async def fetcher(client, source, settings):
        if source.name == "lab":
            items = [
                Candidate(
                    "https://lab.example/release",
                    "New language model",
                    "Weights released.",
                    published_at=utcnow(),
                )
            ]
        elif source.name == "hn":
            items = [
                Candidate(
                    "https://lab.example/release?utm_source=hn",
                    "New language model",
                    published_at=utcnow(),
                    external_id="123",
                    metadata={"hn_points": 100},
                )
            ]
        else:
            items = [
                Candidate(
                    "https://other.example/report",
                    "A language model report",
                    "Independent coverage.",
                    published_at=utcnow(),
                ),
                Candidate(
                    "https://other.example/vision",
                    "Computer vision paper",
                    "Vision research.",
                    published_at=utcnow(),
                ),
            ]
        return FetchResult(items)

    first = await run_pipeline(factory, settings, SimpleNamespace(), embedder, fetcher)
    second = await run_pipeline(factory, settings, SimpleNamespace(), embedder, fetcher)
    assert first["status"] == second["status"] == "succeeded"
    assert first["counts"]["created"] == 3
    assert second["counts"]["created"] == second["counts"]["embedded"] == 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Article)) == 3
        assert session.scalar(select(func.count()).select_from(Observation)) == 4
        clusters = session.scalars(select(Cluster)).all()
        assert sorted(c.cluster_size for c in clusters) == [1, 2]
        language = next(c for c in clusters if c.cluster_size == 2)
        assert (
            session.get(Article, language.primary_article_id).canonical_url
            == "https://lab.example/release"
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ClusterArticle)
                .where(ClusterArticle.is_primary.is_(True))
            )
            == 2
        )


async def test_source_failure_and_model_failure_are_recoverable(factory, settings, embedder):
    with factory() as session:
        session.add_all([make_source("broken"), make_source("healthy")])
        session.commit()

    async def fetcher(client, source, settings):
        if source.name == "broken":
            raise RuntimeError("simulated upstream failure")
        return FetchResult(
            [
                Candidate(
                    "https://healthy.example/release", "New language model", published_at=utcnow()
                )
            ]
        )

    class BrokenEmbedder:
        def encode(self, texts):
            raise RuntimeError("simulated model failure")

    failed = await run_pipeline(factory, settings, SimpleNamespace(), BrokenEmbedder(), fetcher)
    assert failed["status"] == "partial"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Article)) == 1
        assert session.scalar(select(func.count()).select_from(Cluster)) == 0
        broken = session.scalar(select(Source).where(Source.name == "broken"))
        assert broken.last_fetched_at is None and broken.last_error
    retried = await run_pipeline(factory, settings, SimpleNamespace(), embedder, fetcher)
    assert retried["counts"]["created"] == 0
    assert retried["counts"]["embedded"] == retried["counts"]["clustered"] == 1


def test_syndication_keeps_sources_and_prevents_false_short_duplicates(factory, settings):
    with factory() as session:
        first, second = make_source("a"), make_source("b")
        session.add_all([first, second])
        session.flush()
        body = " ".join(f"token{i}" for i in range(500))
        assert store_candidate(
            session, first, Candidate("https://a.example/story", "Story", body), settings
        )
        assert not store_candidate(
            session,
            second,
            Candidate("https://b.example/copy", "Story", body.replace("token123", "edit")),
            settings,
        )
        assert store_candidate(
            session,
            first,
            Candidate("https://a.example/short", "Same title", "Short text"),
            settings,
        )
        assert store_candidate(
            session,
            second,
            Candidate("https://b.example/short", "Same title", "Short text"),
            settings,
        )
        assert session.scalar(select(func.count()).select_from(Observation)) == 4
        assert session.scalar(select(func.count()).select_from(Article)) == 3


@pytest.mark.parametrize("newest_first", [False, True])
@pytest.mark.parametrize(
    "gap",
    [timedelta(days=6), timedelta(days=7), timedelta(days=7, seconds=1), timedelta(days=20)],
)
def test_syndication_time_window_is_symmetric(factory, settings, gap, newest_first):
    with factory() as session:
        source = make_source("publisher")
        session.add(source)
        session.flush()
        older = utcnow() - timedelta(days=30)
        dates = [older, older + gap]
        if newest_first:
            dates.reverse()
        body = " ".join(f"token{i}" for i in range(500))
        for index, published_at in enumerate(dates):
            created = store_candidate(
                session,
                source,
                Candidate(
                    f"https://publisher.example/story-{index}",
                    "Repeated coverage",
                    body,
                    published_at=published_at,
                ),
                settings,
            )
            assert created is (index == 0 or gap > timedelta(days=7))
        expected_articles = 2 if gap > timedelta(days=7) else 1
        assert session.scalar(select(func.count()).select_from(Article)) == expected_articles
        assert session.scalar(select(func.count()).select_from(Observation)) == 2


def test_primary_switch_and_time_window(factory, settings, embedder):
    with factory() as session:
        low, high = make_source("low", 4), make_source("high", 10)
        session.add_all([low, high])
        session.flush()
        for source, url, days in [(low, "one", 0), (high, "two", 0), (high, "old", -5)]:
            store_candidate(
                session,
                source,
                Candidate(
                    f"https://{source.name}.example/{url}",
                    "New language model",
                    published_at=utcnow() + timedelta(days=days),
                ),
                settings,
            )
            article = session.scalar(select(Article).where(Article.url.endswith(url)))
            article.embedding = embedder.encode([article.title])[0]
            article.embedding_model = embedder.model_name
            assign_cluster(session, article, settings)
        session.commit()
        clusters = session.scalars(select(Cluster)).all()
        assert len(clusters) == 2
        pair = next(c for c in clusters if c.cluster_size == 2)
        assert session.get(Article, pair.primary_article_id).url.endswith("/two")
        assert (
            session.scalar(
                select(func.count())
                .select_from(ClusterArticle)
                .where(ClusterArticle.cluster_id == pair.id, ClusterArticle.is_primary.is_(True))
            )
            == 1
        )


async def test_rejected_item_does_not_commit_etag(factory, settings, embedder):
    with factory() as session:
        session.add(make_source("lab"))
        session.commit()

    async def fetcher(*_):
        return FetchResult(
            [
                Candidate("file:///etc/passwd", "Invalid"),
                Candidate("https://lab.example/good", "Good"),
            ],
            state={"etag": "new"},
        )

    result = await run_pipeline(factory, settings, SimpleNamespace(), embedder, fetcher)
    assert result["status"] == "partial"
    with factory() as session:
        source = session.scalar(select(Source))
        assert "etag" not in source.config
        assert session.scalar(select(func.count()).select_from(Article)) == 1


def test_seed_is_idempotent(factory):
    with factory() as session:
        assert seed_sources(session) == 13
        source = session.scalar(select(Source).where(Source.name == "OpenAI"))
        source.is_active = False
        session.commit()
        assert seed_sources(session) == 0
        assert not source.is_active
        assert (
            session.scalar(select(func.count()).select_from(Source).where(Source.type == "rss"))
            == 11
        )


async def test_richer_article_reembeds_without_duplicating_cluster(factory, settings, embedder):
    with factory() as session:
        session.add(make_source("lab"))
        session.commit()
    body = "Short text"

    async def fetcher(*_):
        return FetchResult([Candidate("https://lab.example/model", "New language model", body)])

    await run_pipeline(factory, settings, SimpleNamespace(), embedder, fetcher)
    body = "A much more complete article body that adds technical details and context."
    updated = await run_pipeline(factory, settings, SimpleNamespace(), embedder, fetcher)
    assert updated["counts"]["created"] == 0
    assert updated["counts"]["embedded"] == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Cluster)) == 1
        assert session.scalar(select(Article.body)) == body


def test_primary_syndication_upgrade_retains_permanent_url_alias(factory, settings):
    with factory() as session:
        low, high = make_source("copy", 4), make_source("publisher", 10)
        extra = make_source("community", 5)
        session.add_all([low, high, extra])
        session.flush()
        body = " ".join(f"token{i}" for i in range(500))
        store_candidate(
            session, low, Candidate("https://copy.example/story", "A copy", body), settings
        )
        store_candidate(
            session,
            high,
            Candidate("https://publisher.example/original", "Original", body),
            settings,
        )
        # A later headline-only share of the old copy must still find the original article.
        assert not store_candidate(
            session,
            extra,
            Candidate("https://copy.example/story?utm_source=hn", "Headline only"),
            settings,
        )
        assert session.scalar(select(func.count()).select_from(Article)) == 1
        assert session.scalar(select(Article.canonical_url)) == "https://publisher.example/original"
        assert session.scalar(select(func.count()).select_from(Observation)) == 3


@pytest.mark.parametrize("vector", [[0.0] * 384, [1.0] * 1536, [float("nan")] * 384])
def test_invalid_vectors_rejected(vector):
    with pytest.raises(ValueError):
        validate_vector(vector)


@pytest.mark.parametrize("body_kind", ["feed_summary", "feed_full", "abstract", "extracted"])
@pytest.mark.parametrize("replacement", ["Corrected text", "Same size sentence now"])
async def test_publisher_corrections_invalidate_analysis(
    factory, settings, embedder, body_kind, replacement
):
    with factory() as session:
        session.add(make_source("publisher"))
        session.commit()
    title, body = "Original title", "Four word original sentence"

    async def fetcher(*_):
        return FetchResult(
            [Candidate("https://publisher.example/story", title, body, body_kind=body_kind)]
        )

    await run_pipeline(factory, settings, SimpleNamespace(), embedder, fetcher)
    with factory() as session:
        cluster = session.scalar(select(Cluster))
        cluster.summary = "Old summary"
        cluster.analysis = {"stale": True}
        cluster.analysis_status = "ready"
        cluster.analysis_input_hash = "old"
        session.commit()
    title, body = "Corrected title", replacement
    result = await run_pipeline(factory, settings, SimpleNamespace(), embedder, fetcher)
    assert result["counts"]["created"] == 0
    assert result["counts"]["embedded"] == 1
    with factory() as session:
        article, cluster = session.scalar(select(Article)), session.scalar(select(Cluster))
        assert (article.title, article.body, article.body_kind) == (title, body, body_kind)
        assert cluster.topic == title
        assert cluster.analysis_status == "pending"
        assert cluster.summary is cluster.analysis is cluster.analysis_input_hash is None
        assert session.scalar(select(func.count()).select_from(Cluster)) == 1


@pytest.mark.parametrize("existing_kind", ["extracted", "feed_full", "unknown"])
def test_feed_excerpt_preserves_complete_or_legacy_body(factory, settings, existing_kind):
    with factory() as session:
        source = make_source("publisher")
        session.add(source)
        session.flush()
        original = (
            "The complete original article contains detailed information and supporting context."
        )
        store_candidate(
            session,
            source,
            Candidate(
                "https://publisher.example/story", "Title", original, body_kind=existing_kind
            ),
            settings,
        )
        store_candidate(
            session,
            source,
            Candidate(
                "https://publisher.example/story",
                "Title",
                "Short excerpt",
                body_kind="feed_summary",
            ),
            settings,
        )
        article = session.scalar(select(Article))
        assert article.body == original
        assert article.body_kind == existing_kind


async def test_fallback_coverage_diagnostics_survive_partial_run(factory, settings, embedder):
    with factory() as session:
        source = make_source("arxiv")
        source.config = {"etag": "old"}
        session.add(source)
        session.commit()

    async def fetcher(*_):
        return FetchResult(
            [],
            state={
                "fetch_mode": "rss_fallback",
                "scope_note": "Latest announcements only",
                "etag": "new",
            },
            warnings=["API unavailable; RSS is an incomplete lookback"],
        )

    result = await run_pipeline(factory, settings, SimpleNamespace(), embedder, fetcher)
    assert result["status"] == "partial"
    with factory() as session:
        source = session.scalar(select(Source))
        assert source.config == {
            "etag": "old",
            "fetch_mode": "rss_fallback",
            "scope_note": "Latest announcements only",
        }
        assert source.last_error


@pytest.mark.parametrize("weaker_first", [False, True])
def test_representative_body_always_belongs_to_its_publisher(factory, settings, weaker_first):
    with factory() as session:
        official, community = make_source("official", 10), make_source("community", 4)
        session.add_all([official, community])
        session.flush()
        official_body = "The official publisher announces a corrected specification."
        community_body = (
            "Community speculation with much more text and unsupported capabilities " * 10
        )
        rows = [(official, official_body), (community, community_body)]
        if weaker_first:
            rows.reverse()
        for source, body in rows:
            store_candidate(
                session,
                source,
                Candidate("https://official.example/story", "Product announcement", body),
                settings,
            )
        article = session.scalar(select(Article))
        assert article.source_id == official.id
        assert article.body == official_body
        assert session.scalar(select(func.count()).select_from(Observation)) == 2


def test_identical_publisher_text_identifies_legacy_body_for_later_corrections(factory, settings):
    with factory() as session:
        source = make_source("publisher")
        session.add(source)
        session.flush()
        for body, kind in [
            ("The original full feed summary", "unknown"),
            ("The original full feed summary", "feed_summary"),
            ("Corrected shorter summary", "feed_summary"),
        ]:
            store_candidate(
                session,
                source,
                Candidate("https://publisher.example/story", "Title", body, body_kind=kind),
                settings,
            )
        article = session.scalar(select(Article))
        assert article.body == "Corrected shorter summary"
        assert article.body_kind == "feed_summary"
