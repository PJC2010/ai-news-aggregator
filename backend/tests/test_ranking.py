from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event

from app.models import Article, Cluster, ClusterArticle, Observation, Source
from app.services.processing.ranking import (
    RANKING_VERSION,
    RankingSignals,
    load_ranking_signals,
    rank_cluster,
    ranking_key,
)

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)


def cluster_at(age_hours=0, significance=None, cluster_id=1):
    return SimpleNamespace(
        id=UUID(int=cluster_id),
        latest_published_at=NOW - timedelta(hours=age_hours),
        significance_score=significance,
    )


def corroboration(publishers=1, categories=1):
    return RankingSignals(
        article_ids={UUID(int=i + 1) for i in range(publishers)},
        publishers={f"publisher-{i}.example" for i in range(publishers)},
        categories={f"category-{i}" for i in range(categories)},
    )


def observe(signals, story_id, *, points=0, comments=0, seen_at=NOW, source_type="hackernews"):
    signals.add_observation(
        source_type,
        "community",
        str(story_id),
        {"hn_item_id": story_id, "hn_points": points, "hn_comments": comments},
        seen_at,
        uuid4(),
    )


def test_recency_decays_total_score_with_36_hour_half_life_and_future_clamp():
    signals = corroboration(publishers=5, categories=5)
    observe(signals, 100, points=1500)
    fresh = rank_cluster(cluster_at(significance=10), signals, NOW)
    older = rank_cluster(cluster_at(age_hours=36, significance=10), signals, NOW)
    future = rank_cluster(cluster_at(age_hours=-12, significance=10), signals, NOW)
    assert fresh["rank_version"] == RANKING_VERSION
    assert fresh["rank_score"] == 100
    assert older["rank_score"] == 50
    assert future["rank_score"] == fresh["rank_score"]


def test_missing_significance_is_neutral_and_explicitly_unavailable():
    missing = rank_cluster(cluster_at(), RankingSignals(), NOW)
    neutral = rank_cluster(cluster_at(significance=5), RankingSignals(), NOW)
    assert missing["rank_score"] == neutral["rank_score"] == 22.5
    component = missing["rank_components"]["technical_significance"]
    assert component["available"] is False
    assert component["score"] is None
    assert component["value"] == 0.5
    assert neutral["rank_components"]["technical_significance"]["available"] is True


def test_observation_diversity_never_turns_one_deduplicated_article_into_corroboration():
    signals = corroboration(publishers=1, categories=1)
    for index in range(12):
        signals.add_observation("rss", f"category-{index}", str(index), {}, NOW, uuid4())
    result = rank_cluster(cluster_at(), signals, NOW)
    diversity = result["rank_components"]["diversity"]
    assert diversity["value"] == 0
    assert diversity["independent_categories"] == diversity["independent_publishers"] == 1
    independent = rank_cluster(cluster_at(), corroboration(publishers=3, categories=3), NOW)
    assert independent["rank_components"]["diversity"]["value"] == 0.5
    assert independent["rank_score"] > result["rank_score"]


def test_same_publisher_articles_do_not_add_publisher_corroboration():
    signals = RankingSignals(categories={"research"})
    for index in range(8):
        host = "www.publisher.example" if index % 2 else "publisher.example"
        signals.add_article(uuid4(), f"https://{host}/{index}", uuid4())
    result = rank_cluster(cluster_at(), signals, NOW)
    assert result["rank_components"]["diversity"]["value"] == 0


def test_hn_engagement_uses_latest_counters_once_per_external_story_across_observations():
    signals = corroboration()
    observe(signals, 123, points=400, comments=90, seen_at=NOW - timedelta(hours=1))
    observe(signals, "123", points=40, comments=9)
    observe(signals, 123, points=900, seen_at=NOW - timedelta(hours=2))
    observe(signals, 123, points=999, source_type="rss")
    result = rank_cluster(cluster_at(), signals, NOW)
    one_observation = corroboration()
    observe(one_observation, 123, points=40, comments=9)
    assert result["rank_score"] == rank_cluster(cluster_at(), one_observation, NOW)["rank_score"]
    assert result["rank_components"]["engagement"]["hn_stories"] == 1
    observe(signals, 124, points=40, comments=9)
    assert rank_cluster(cluster_at(), signals, NOW)["rank_score"] > result["rank_score"]


def test_engagement_and_diversity_are_bounded_even_for_large_counts():
    signals = corroboration(publishers=200, categories=200)
    for index in range(100):
        observe(signals, index + 1, points=1_000_000, comments=1_000_000)
    result = rank_cluster(cluster_at(significance=10), signals, NOW)
    assert result["rank_score"] == 100
    assert result["rank_components"]["engagement"]["value"] == 1
    assert result["rank_components"]["diversity"]["value"] == 1


@pytest.mark.parametrize("invalid", [None, "1000", -10, float("nan"), float("inf"), True])
def test_malformed_engagement_cannot_poison_rank_or_inflate_it(invalid):
    signals = corroboration()
    observe(signals, 123, points=invalid, comments=invalid)
    result = rank_cluster(cluster_at(), signals, NOW)
    assert result["rank_score"] == 22.5
    assert result["rank_components"]["engagement"]["value"] == 0


def test_ranking_ties_use_timestamp_then_uuid_and_accept_sqlite_naive_datetimes():
    signals = RankingSignals()
    old = cluster_at(age_hours=12, cluster_id=3)
    recent_b = cluster_at(cluster_id=2)
    recent_a = cluster_at(cluster_id=1)
    # Equal scores can occur after saturation/rounding; timestamp is the second key.
    forced_tie = {"rank_score": 10.0}
    assert sorted(
        [old, recent_b, recent_a], key=lambda cluster: ranking_key(cluster, forced_tie)
    ) == [recent_a, recent_b, old]
    recent_a.latest_published_at = recent_a.latest_published_at.replace(tzinfo=None)
    assert rank_cluster(recent_a, signals, NOW)["rank_score"] == 22.5


def test_load_ranking_signals_batches_all_clusters_and_deduplicates_hn_ids(factory):
    with factory() as session:
        sources = [
            Source(
                name=f"HN mirror {index}",
                url=f"https://hn-{index}.example",
                type="hackernews",
                category="community",
            )
            for index in range(2)
        ]
        session.add_all(sources)
        session.flush()
        clusters = []
        for index in range(12):
            article = Article(
                source_id=sources[0].id,
                url=f"https://publisher.example/{index}",
                canonical_url=f"https://publisher.example/{index}",
                url_hash=f"hash-{index}",
                title=f"Article {index}",
            )
            session.add(article)
            session.flush()
            cluster = Cluster(
                topic=article.title,
                primary_article_id=article.id,
                latest_published_at=NOW,
            )
            session.add(cluster)
            session.flush()
            session.add(
                ClusterArticle(
                    cluster_id=cluster.id,
                    article_id=article.id,
                    is_primary=True,
                    similarity_score=1,
                )
            )
            for source in sources:
                session.add(
                    Observation(
                        article_id=article.id,
                        source_id=source.id,
                        external_id=str(index),
                        url=article.url,
                        url_hash=article.url_hash,
                        extra={"hn_item_id": index, "hn_points": 10},
                        seen_at=NOW,
                    )
                )
            clusters.append(cluster)
        session.commit()
        statements = []

        def count_statements(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(session.bind, "before_cursor_execute", count_statements)
        try:
            signals = load_ranking_signals(session, [cluster.id for cluster in clusters])
        finally:
            event.remove(session.bind, "before_cursor_execute", count_statements)
        assert len(statements) == 1
        assert len(signals) == 12
        assert all(len(signal.hn_stories) == 1 for signal in signals.values())
        assert all(len(signal.article_ids) == 1 for signal in signals.values())
