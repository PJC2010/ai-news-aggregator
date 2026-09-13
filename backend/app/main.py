import hmac
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

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
)
from app.services.processing.ranking import (
    RankingSignals,
    load_ranking_signals,
    rank_cluster,
    ranking_key,
)

app = FastAPI(title="AI News Aggregator — Intelligence Preview", version="0.2.0")


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
    except Exception as exc:
        raise HTTPException(503, "Database or vector extension is not ready") from exc
    return {"status": "ready"}


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
