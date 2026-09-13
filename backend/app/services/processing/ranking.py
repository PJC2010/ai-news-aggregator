"""Versioned, bounded editorial ranking; no model calls or user personalization.

v1 is 100 * 2^(-age_hours/36) * (0.45 * significance + 0.30 * diversity
+ 0.25 * engagement). Significance is the shared analysis's validated 1–10 score
divided by ten; missing analysis is neutral (0.5) and marked unavailable.
Diversity averages publisher and source-category corroboration, each saturated
at five and bounded by the number of deduplicated articles. Engagement is
logarithmic HN points + 2 * comments, saturated at 1,500. These are editorial
heuristics, not calibrated probabilities or evidence that an event is verified.

Publisher identity uses each deduplicated article's canonical hostname, not the
number of feed observations. Hostnames are an approximation: different domains
may share an owner. HN story IDs are deduplicated across observations and feeds;
only the most recently observed counters for each story contribute.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Article, Cluster, ClusterArticle, Observation, Source

RANKING_VERSION = "editorial-v1"
WEIGHTS = {"technical_significance": 0.45, "diversity": 0.30, "engagement": 0.25}
RECENCY_HALF_LIFE_HOURS = 36
ENGAGEMENT_SATURATION = 1500


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def nonnegative_number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return 0.0
    try:
        number = float(value)
    except OverflowError:
        return float(ENGAGEMENT_SATURATION) if value > 0 else 0.0
    return max(0.0, number) if math.isfinite(number) else 0.0


def publisher_origin(url: str, source_id: UUID) -> str:
    try:
        host = urlsplit(url).hostname
    except ValueError:
        host = None
    return host.lower().removeprefix("www.") if host else f"source:{source_id}"


@dataclass
class RankingSignals:
    article_ids: set[UUID] = field(default_factory=set)
    publishers: set[str] = field(default_factory=set)
    categories: set[str] = field(default_factory=set)
    # story ID -> (observation timestamp, deterministic tie key, points, comments)
    hn_stories: dict[str, tuple[datetime, str, float, float]] = field(default_factory=dict)

    def add_article(self, article_id: UUID, url: str, source_id: UUID):
        self.article_ids.add(article_id)
        self.publishers.add(publisher_origin(url, source_id))

    def add_observation(
        self, source_type, category, external_id, metadata, seen_at, observation_id
    ):
        if category:
            self.categories.add(category)
        if source_type != "hackernews" or not isinstance(metadata, dict):
            return
        story_id = str(metadata.get("hn_item_id") or external_id or "")
        if not story_id:
            return
        candidate = (
            aware(seen_at),
            str(observation_id),
            min(nonnegative_number(metadata.get("hn_points")), ENGAGEMENT_SATURATION),
            min(nonnegative_number(metadata.get("hn_comments")), ENGAGEMENT_SATURATION),
        )
        previous = self.hn_stories.get(story_id)
        if previous is None or candidate[:2] > previous[:2]:
            self.hn_stories[story_id] = candidate


def load_ranking_signals(session: Session, cluster_ids: list[UUID]) -> dict[UUID, RankingSignals]:
    """Load lightweight provenance columns in batches, without loading article bodies/vectors."""
    signals = defaultdict(RankingSignals)
    for start in range(0, len(cluster_ids), 500):
        rows = session.execute(
            select(
                ClusterArticle.cluster_id,
                Article.id,
                Article.canonical_url,
                Article.source_id,
                Source.type,
                Source.category,
                Observation.external_id,
                Observation.extra,
                Observation.seen_at,
                Observation.id,
            )
            .join(Article, Article.id == ClusterArticle.article_id)
            .outerjoin(Observation, Observation.article_id == Article.id)
            .outerjoin(Source, Source.id == Observation.source_id)
            .where(ClusterArticle.cluster_id.in_(cluster_ids[start : start + 500]))
        )
        for row in rows:
            cluster_id, article_id, url, source_id, kind, category, ext_id, extra, seen, oid = row
            signal = signals[cluster_id]
            signal.add_article(article_id, url, source_id)
            if oid is not None:
                signal.add_observation(kind, category, ext_id, extra, seen, oid)
    return signals


def rank_cluster(cluster: Cluster, signals: RankingSignals, now: datetime) -> dict:
    age_hours = max(0.0, (aware(now) - aware(cluster.latest_published_at)).total_seconds() / 3600)
    independent_publishers = min(len(signals.article_ids), len(signals.publishers))
    independent_categories = min(len(signals.article_ids), len(signals.categories))
    hn_points = sum(item[2] for item in signals.hn_stories.values())
    hn_comments = sum(item[3] for item in signals.hn_stories.values())
    engagement = min(hn_points + 2 * hn_comments, ENGAGEMENT_SATURATION)
    significance = cluster.significance_score
    available = (
        isinstance(significance, (float, int))
        and not isinstance(significance, bool)
        and math.isfinite(significance)
        and 1 <= significance <= 10
    )
    recency = 2 ** (-age_hours / RECENCY_HALF_LIFE_HOURS)
    publisher_diversity = min(max(independent_publishers - 1, 0) / 4, 1.0)
    category_diversity = min(max(independent_categories - 1, 0) / 4, 1.0)
    normalized = {
        "diversity": (publisher_diversity + category_diversity) / 2,
        "engagement": math.log1p(engagement) / math.log1p(ENGAGEMENT_SATURATION),
        "technical_significance": significance / 10 if available else 0.5,
    }
    components = {
        name: {
            "value": round(value, 6),
            "weight": WEIGHTS[name],
            "points_before_decay": round(100 * WEIGHTS[name] * value, 6),
            "points": round(100 * recency * WEIGHTS[name] * value, 6),
        }
        for name, value in normalized.items()
    }
    components["diversity"].update(
        independent_publishers=independent_publishers,
        independent_categories=independent_categories,
        publisher_value=publisher_diversity,
        category_value=category_diversity,
        deduplicated_articles=len(signals.article_ids),
    )
    components["engagement"].update(
        hn_stories=len(signals.hn_stories), hn_points=hn_points, hn_comments=hn_comments
    )
    components["technical_significance"].update(
        available=available, score=significance if available else None
    )
    rank_score = round(sum(component["points"] for component in components.values()), 6)
    components["recency"] = {
        "value": round(recency, 6),
        "age_hours": round(age_hours, 3),
        "half_life_hours": RECENCY_HALF_LIFE_HOURS,
    }
    return {
        "rank_score": rank_score,
        "rank_components": components,
        "rank_version": RANKING_VERSION,
    }


def ranking_key(cluster: Cluster, ranking: dict) -> tuple:
    """Descending score/time and ascending UUID keep ties stable across requests."""
    return (
        -ranking["rank_score"],
        -aware(cluster.latest_published_at).timestamp(),
        str(cluster.id),
    )
