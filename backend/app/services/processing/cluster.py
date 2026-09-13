from datetime import UTC, timedelta

import numpy as np
from sqlalchemy import func, select

from app.config import EMBEDDING_SPACE, Settings
from app.models import Article, Cluster, ClusterArticle, Observation, Source, utcnow


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def cosine(left, right) -> float:
    a, b = np.asarray(left), np.asarray(right)
    return float(np.clip(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)), -1, 1))


def authority(session, article: Article) -> int:
    return (
        session.scalar(
            select(func.max(Source.authority_score))
            .join(
                Observation,
                Observation.source_id == Source.id,
            )
            .where(Observation.article_id == article.id)
        )
        or 1
    )


def quality(session, article: Article):
    # Authority dominates completeness; ties are stable across replays.
    return (
        authority(session, article),
        min(len(article.body.split()), 3000),
        article.canonical_url,
    )


def invalidate_analysis(cluster):
    cluster.summary = None
    cluster.analysis = None
    cluster.analysis_input_hash = None
    cluster.significance_score = None
    cluster.event_type = None
    cluster.analysis_status = "pending"
    cluster.analysis_error = None
    cluster.analyzed_at = None


def refresh_cluster(session, cluster_id):
    cluster = session.get(Cluster, cluster_id)
    members = session.scalars(
        select(Article)
        .join(ClusterArticle)
        .where(
            ClusterArticle.cluster_id == cluster_id,
        )
    ).all()
    primary = max(members, key=lambda item: quality(session, item))
    links = session.scalars(
        select(ClusterArticle).where(
            ClusterArticle.cluster_id == cluster_id,
        )
    ).all()
    for link in links:
        link.is_primary = False
    session.flush()  # Satisfy the partial unique index during a primary switch.
    for link in links:
        link.is_primary = link.article_id == primary.id
    cluster.primary_article_id = primary.id
    cluster.topic = primary.title
    cluster.cluster_size = len(members)
    cluster.latest_published_at = max(aware(a.published_at or a.fetched_at) for a in members)
    cluster.updated_at = utcnow()
    invalidate_analysis(cluster)
    session.flush()


def assign_cluster(session, article: Article, settings: Settings):
    existing = session.scalar(select(ClusterArticle).where(ClusterArticle.article_id == article.id))
    if existing:
        return session.get(Cluster, existing.cluster_id)
    if article.embedding is None or article.embedding_model != EMBEDDING_SPACE:
        raise ValueError("Cannot cluster an article without an embedding in the configured space")
    published = aware(article.published_at or article.fetched_at)
    window = timedelta(hours=settings.cluster_window_hours)
    candidates = session.execute(
        select(Cluster, Article)
        .join(
            Article,
            Cluster.primary_article_id == Article.id,
        )
        .where(
            Cluster.latest_published_at >= published - window,
            Cluster.latest_published_at <= published + window,
            Article.embedding_model == article.embedding_model,
        )
        .order_by(Cluster.created_at, Cluster.id)
    ).all()
    best, best_score = None, settings.cluster_similarity
    for cluster, primary in candidates:
        # Compare event time as well as activity time to avoid long-running topic chains.
        if abs(aware(primary.published_at or primary.fetched_at) - published) > window:
            continue
        similarity = cosine(article.embedding, primary.embedding)
        if similarity >= best_score:
            best, best_score = cluster, similarity
    if best is None:
        best = Cluster(
            topic=article.title, primary_article_id=article.id, latest_published_at=published
        )
        session.add(best)
        session.flush()
        best_score = 1.0
    session.add(
        ClusterArticle(
            cluster_id=best.id, article_id=article.id, is_primary=False, similarity_score=best_score
        )
    )
    session.flush()
    refresh_cluster(session, best.id)
    return best
