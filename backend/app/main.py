import hmac
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from sqlalchemy import false, func, or_, select, text
from sqlalchemy.orm import Session

from app.auth import Identity, require_user
from app.config import get_settings
from app.database import get_session
from app.models import (
    AnalysisCall,
    AnalysisRun,
    Article,
    Cluster,
    ClusterArticle,
    Observation,
    PipelineRun,
    Source,
    UserTopic,
)
from app.preferences import (
    TOPICS,
    TopicsUpdate,
    ensure_profile,
    profile_payload,
    save_topics,
    topic_match,
)
from app.services.processing.ranking import (
    RankingSignals,
    load_ranking_signals,
    rank_cluster,
    ranking_key,
)

app = FastAPI(title="AI News Aggregator", version="0.3.0")


@app.middleware("http")
async def private_responses(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/me", "/feed", "/clusters", "/internal")):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Authorization, X-Operator-Key"
    elif request.url.path.startswith("/public/"):
        response.headers["Cache-Control"] = "public, max-age=60, s-maxage=300, stale-while-revalidate=600"
    return response


def require_operator(x_operator_key: str | None = Header(default=None)):
    key = get_settings().operator_api_key
    if not key:
        raise HTTPException(503, "Configure OPERATOR_API_KEY to enable pipeline inspection")
    if not x_operator_key or not hmac.compare_digest(x_operator_key, key):
        raise HTTPException(401, "Invalid operator key")


@app.get("/health")
def health():
    return {"status": "ok", "milestone": "shared-analysis"}


@app.get("/health/ready")
def ready(session: Session = Depends(get_session)):
    try:
        session.execute(text("SELECT 1 FROM sources LIMIT 1"))
        session.execute(text("SELECT '[1,0]'::vector"))
        session.execute(text("SELECT 1 FROM analysis_calls LIMIT 1"))
        session.execute(text("SELECT 1 FROM users LIMIT 1"))
        session.execute(text("SELECT 1 FROM user_topics LIMIT 1"))
    except Exception as exc:
        raise HTTPException(503, "Database or vector extension is not ready") from exc
    return {"status": "ready"}


@app.get("/me")
def me(identity: Identity = Depends(require_user), session: Session = Depends(get_session)):
    return profile_payload(session, ensure_profile(session, identity))


@app.put("/me/topics")
def update_topics(
    update: TopicsUpdate,
    identity: Identity = Depends(require_user),
    session: Session = Depends(get_session),
):
    return save_topics(session, identity, update)


def customer_payload(payload):
    # Provider errors and raw observation metadata belong to operator inspection.
    payload.pop("analysis_error", None)
    for source in payload.get("coverage", []):
        source.pop("signals", None)
    return payload


PUBLIC_COVERAGE_LIMIT = 10


def public_event_payload(session: Session, cluster: Cluster, *, detail: bool = False):
    """Serialize the deliberately small, stable public event contract.

    Keep this separate from the customer serializer so adding subscriber fields to
    the dashboard cannot accidentally publish them.
    """
    article = session.get(Article, cluster.primary_article_id)
    result = {
        "id": cluster.id,
        "title": article.title,
        "summary": cluster.summary,
        "significance_score": cluster.significance_score,
        "event_type": cluster.event_type,
        "published_at": cluster.latest_published_at,
        "primary_link": article.canonical_url,
        "source_count": cluster.cluster_size,
    }
    if detail:
        rows = session.execute(
            select(Article, Source, Observation)
            .join(ClusterArticle, ClusterArticle.article_id == Article.id)
            .join(Observation, Observation.article_id == Article.id)
            .join(Source, Source.id == Observation.source_id)
            .where(ClusterArticle.cluster_id == cluster.id)
            .order_by(Source.authority_score.desc(), Source.name, Article.id)
            .limit(PUBLIC_COVERAGE_LIMIT)
        ).all()
        result["coverage"] = [
            {"title": item.title, "source": source.name, "url": observation.url}
            for item, source, observation in rows
        ]
        result["coverage_limit"] = PUBLIC_COVERAGE_LIMIT
    return result


@app.get("/public/feed")
def public_feed(
    session: Session = Depends(get_session),
    limit: int = Query(12, ge=1, le=50),
    offset: int = Query(0, ge=0, le=10000),
):
    now = datetime.now(UTC)
    statement = select(Cluster).where(Cluster.latest_published_at <= now)
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    clusters = session.scalars(
        statement.order_by(Cluster.latest_published_at.desc(), Cluster.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "items": [public_event_payload(session, cluster) for cluster in clusters],
        "total": total,
        "limit": limit,
        "offset": offset,
        "as_of": now,
    }


@app.get("/public/events/{cluster_id}")
def public_event(cluster_id: UUID, session: Session = Depends(get_session)):
    cluster = session.scalar(
        select(Cluster).where(
            Cluster.id == cluster_id, Cluster.latest_published_at <= datetime.now(UTC)
        )
    )
    if not cluster:
        raise HTTPException(404, "Event not found")
    return public_event_payload(session, cluster, detail=True)


@app.get("/feed")
def customer_feed(
    identity: Identity = Depends(require_user),
    session: Session = Depends(get_session),
    limit: int = Query(12, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
    sort: Literal["ranked", "latest"] = Query("ranked"),
    q: str = Query("", max_length=200),
    topic: str | None = Query(None, max_length=60),
    following: bool = False,
    window: Literal["week", "today", "all"] = Query("week"),
    event_type: Literal[
        "model_release",
        "paper",
        "funding",
        "regulation",
        "research_breakthrough",
        "tool_release",
        "other",
    ]
    | None = Query(None),
):
    now = datetime.now(UTC)
    statement = select(Cluster).join(Article, Article.id == Cluster.primary_article_id)
    if window == "week":
        statement = statement.where(Cluster.latest_published_at >= now - timedelta(days=7))
    elif window == "today":
        statement = statement.where(
            Cluster.latest_published_at >= now.replace(hour=0, minute=0, second=0, microsecond=0)
        )
    statement = statement.where(Cluster.latest_published_at <= now)
    if q.strip():
        statement = statement.where(
            or_(
                *(
                    column.icontains(q.strip(), autoescape=True)
                    for column in (Cluster.topic, Cluster.summary, Article.title)
                )
            )
        )
    if topic:
        if topic not in TOPICS:
            raise HTTPException(422, "Unknown topic")
        statement = statement.where(topic_match(topic))
    if following:
        topics = list(
            session.scalars(select(UserTopic.topic).where(UserTopic.user_id == identity.id))
        )
        predicates = [topic_match(value) for value in topics if value in TOPICS]
        statement = statement.where(or_(*predicates) if predicates else false())
    if event_type:
        statement = statement.where(Cluster.event_type == event_type)
    page = cluster_page(session, statement, limit=limit, offset=offset, sort=sort)
    page["items"] = [customer_payload(item) for item in page["items"]]
    return {**page, "as_of": now, "window": window, "timezone": "UTC"}


@app.get("/feed/{cluster_id}")
def customer_detail(
    cluster_id: UUID,
    identity: Identity = Depends(require_user),
    session: Session = Depends(get_session),
):
    cluster = session.get(Cluster, cluster_id)
    if not cluster:
        raise HTTPException(404, "Event not found")
    return customer_payload(cluster_payload(session, cluster, detail=True))


@app.get("/internal/analysis", dependencies=[Depends(require_operator)])
def analysis_status(session: Session = Depends(get_session)):
    settings = get_settings()
    history = list(
        session.scalars(select(AnalysisRun).order_by(AnalysisRun.started_at.desc()).limit(20))
    )
    calls = list(
        session.scalars(select(AnalysisCall).order_by(AnalysisCall.created_at.desc()).limit(20))
    )
    return {
        "provider": "deepseek",
        "credentials_configured": bool(settings.deepseek_api_key.get_secret_value()),
        "automatic_analysis_enabled": settings.analysis_enabled,
        "summary_model": settings.summary_model,
        "analysis_model": settings.analysis_model,
        "run_budget_usd": settings.analysis_budget_usd,
        "cluster_limit": settings.analysis_cluster_limit,
        "estimated_total_cost_usd": session.scalar(
            select(func.coalesce(func.sum(AnalysisCall.estimated_cost_usd), 0))
        ),
        "cost_note": (
            "Conservative peak-rate estimates; attempts without usage retain their "
            "pre-request reservation. Provider billing is authoritative."
        ),
        "runs": [
            {
                "id": run.id,
                "status": run.status,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "counts": run.counts,
                "errors": run.errors,
                "estimated_cost_usd": run.estimated_cost_usd,
            }
            for run in history
        ],
        "recent_calls": [
            {
                "id": call.id,
                "cluster_id": call.cluster_id,
                "stage": call.stage,
                "status": call.status,
                "model": call.model,
                "returned_model": call.returned_model,
                "prompt_version": call.prompt_version,
                "input_tokens": call.input_tokens,
                "cached_input_tokens": call.cached_input_tokens,
                "output_tokens": call.output_tokens,
                "estimated_cost_usd": call.estimated_cost_usd,
                "cost_is_upper_bound": call.cost_is_upper_bound,
                "pricing_version": call.pricing_version,
                "error": call.error,
                "created_at": call.created_at,
            }
            for call in calls
        ],
    }


def cluster_payload(session, cluster, detail=False, *, article=None, ranking=None):
    if article is None:
        article = session.get(Article, cluster.primary_article_id)
    if ranking is None:
        signals = load_ranking_signals(session, [cluster.id])
        ranking = rank_cluster(
            cluster, signals.get(cluster.id, RankingSignals()), datetime.now(UTC)
        )
    result = {
        "id": cluster.id,
        "topic": cluster.topic,
        "cluster_size": cluster.cluster_size,
        "primary_article": {
            "id": article.id,
            "title": article.title,
            "url": article.canonical_url,
            "published_at": article.published_at,
        },
        "summary": cluster.summary,
        "analysis": cluster.analysis,
        "analysis_status": cluster.analysis_status,
        "analysis_error": cluster.analysis_error,
        "analyzed_at": cluster.analyzed_at,
        "significance_score": cluster.significance_score,
        "event_type": cluster.event_type,
        "latest_published_at": cluster.latest_published_at,
        "created_at": cluster.created_at,
        **ranking,
    }
    if detail:
        rows = session.execute(
            select(Article, Source, Observation)
            .join(
                ClusterArticle,
                ClusterArticle.article_id == Article.id,
            )
            .join(Observation, Observation.article_id == Article.id)
            .join(
                Source,
                Source.id == Observation.source_id,
            )
            .where(ClusterArticle.cluster_id == cluster.id)
            .order_by(
                Source.authority_score.desc(),
                Source.name,
            )
        ).all()
        result["coverage"] = [
            {
                "article_id": a.id,
                "title": a.title,
                "source": s.name,
                "source_category": s.category,
                "url": o.url,
                "signals": o.extra,
            }
            for a, s, o in rows
        ]
    return result


def cluster_page(session, statement, *, limit, offset, sort):
    count = session.scalar(select(func.count()).select_from(statement.subquery()))
    if sort == "latest":
        statement = (
            statement.order_by(Cluster.latest_published_at.desc(), Cluster.id)
            .offset(offset)
            .limit(limit)
        )
    rows = session.scalars(statement).all()
    now = datetime.now(UTC)
    signals = load_ranking_signals(session, [cluster.id for cluster in rows])
    rankings = {
        cluster.id: rank_cluster(cluster, signals.get(cluster.id, RankingSignals()), now)
        for cluster in rows
    }
    if sort == "ranked":
        # Rank the entire filtered candidate set before slicing for correct global pages.
        rows.sort(key=lambda cluster: ranking_key(cluster, rankings[cluster.id]))
        rows = rows[offset : offset + limit]
    articles = (
        {
            article.id: article
            for article in session.scalars(
                select(Article).where(
                    Article.id.in_({cluster.primary_article_id for cluster in rows})
                )
            )
        }
        if rows
        else {}
    )
    return {
        "total": count,
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "items": [
            cluster_payload(
                session,
                cluster,
                article=articles[cluster.primary_article_id],
                ranking=rankings[cluster.id],
            )
            for cluster in rows
        ],
    }


@app.get("/clusters/today", dependencies=[Depends(require_operator)])
def today(
    session: Session = Depends(get_session),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: Literal["ranked", "latest"] = Query("ranked"),
    topic: str | None = Query(None, min_length=1, max_length=200),
):
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    statement = select(Cluster).where(
        Cluster.latest_published_at >= start,
        Cluster.latest_published_at < start + timedelta(days=1),
    )
    if topic:
        statement = statement.where(Cluster.topic.icontains(topic, autoescape=True))
    return {
        "date": start.date(),
        "timezone": "UTC",
        **cluster_page(session, statement, limit=limit, offset=offset, sort=sort),
    }


@app.get("/clusters", dependencies=[Depends(require_operator)])
def clusters(
    session: Session = Depends(get_session),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    topic: str | None = Query(None, min_length=1, max_length=200),
    sort: Literal["ranked", "latest"] = Query("ranked"),
):
    statement = select(Cluster)
    if topic:
        statement = statement.where(Cluster.topic.icontains(topic, autoescape=True))
    return cluster_page(session, statement, limit=limit, offset=offset, sort=sort)


@app.get("/clusters/{cluster_id}", dependencies=[Depends(require_operator)])
def cluster_detail(cluster_id: UUID, session: Session = Depends(get_session)):
    cluster = session.get(Cluster, cluster_id)
    if not cluster:
        raise HTTPException(404, "Cluster not found")
    return cluster_payload(session, cluster, detail=True)


@app.get("/internal/sources", dependencies=[Depends(require_operator)])
def sources(session: Session = Depends(get_session)):
    return [
        {
            "id": source.id,
            "name": source.name,
            "url": source.url,
            "type": source.type,
            "fetch_mode": (source.config or {}).get("fetch_mode"),
            "scope_note": (source.config or {}).get("scope_note"),
            "is_active": source.is_active,
            "last_fetched_at": source.last_fetched_at,
            "last_error": source.last_error,
        }
        for source in session.scalars(select(Source).order_by(Source.name))
    ]


@app.get("/internal/runs", dependencies=[Depends(require_operator)])
def runs(session: Session = Depends(get_session)):
    return [
        {
            "id": run.id,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "counts": run.counts,
            "errors": run.errors,
        }
        for run in session.scalars(
            select(PipelineRun)
            .order_by(
                PipelineRun.started_at.desc(),
            )
            .limit(20)
        )
    ]
