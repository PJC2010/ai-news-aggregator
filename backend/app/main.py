import hmac
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_session
from app.models import Article, Cluster, ClusterArticle, Observation, PipelineRun, Source

app = FastAPI(title="AI News Aggregator — Pipeline Preview", version="0.1.0")


def require_operator(x_operator_key: str | None = Header(default=None)):
    key = get_settings().operator_api_key
    if not key:
        raise HTTPException(503, "Configure OPERATOR_API_KEY to enable pipeline inspection")
    if not x_operator_key or not hmac.compare_digest(x_operator_key, key):
        raise HTTPException(401, "Invalid operator key")


@app.get("/health")
def health():
    return {"status": "ok", "milestone": "pipeline-core"}


@app.get("/health/ready")
def ready(session: Session = Depends(get_session)):
    try:
        session.execute(text("SELECT 1 FROM sources LIMIT 1"))
        session.execute(text("SELECT '[1,0]'::vector"))
    except Exception as exc:
        raise HTTPException(503, "Database or vector extension is not ready") from exc
    return {"status": "ready"}


def cluster_payload(session, cluster, detail=False):
    article = session.get(Article, cluster.primary_article_id)
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
        "analysis_status": "ready" if cluster.analysis else "not_implemented",
        "significance_score": cluster.significance_score,
        "event_type": cluster.event_type,
        "latest_published_at": cluster.latest_published_at,
        "created_at": cluster.created_at,
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


@app.get("/clusters/today", dependencies=[Depends(require_operator)])
def today(session: Session = Depends(get_session), limit: int = Query(20, ge=1, le=100)):
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    clusters = session.scalars(
        select(Cluster)
        .where(
            Cluster.latest_published_at >= start,
            Cluster.latest_published_at < start + timedelta(days=1),
        )
        .order_by(Cluster.latest_published_at.desc(), Cluster.id)
        .limit(limit)
    )
    return {
        "date": start.date(),
        "timezone": "UTC",
        "items": [cluster_payload(session, cluster) for cluster in clusters],
    }


@app.get("/clusters", dependencies=[Depends(require_operator)])
def clusters(
    session: Session = Depends(get_session),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    topic: str | None = Query(None, min_length=1, max_length=200),
):
    statement = select(Cluster)
    if topic:
        statement = statement.where(Cluster.topic.icontains(topic, autoescape=True))
    count = session.scalar(select(func.count()).select_from(statement.subquery()))
    rows = session.scalars(
        statement.order_by(
            Cluster.latest_published_at.desc(),
            Cluster.id,
        )
        .offset(offset)
        .limit(limit)
    )
    return {
        "total": count,
        "limit": limit,
        "offset": offset,
        "items": [cluster_payload(session, cluster) for cluster in rows],
    }


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
