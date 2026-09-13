import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import EMBEDDING_DIMENSIONS


def utcnow():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


Json = JSON().with_variant(JSONB(), "postgresql")
Embedding = JSON(none_as_null=True).with_variant(Vector(EMBEDDING_DIMENSIONS), "postgresql")


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (CheckConstraint("authority_score BETWEEN 1 AND 10"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text, unique=True)
    type: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(30))
    authority_score: Mapped[int] = mapped_column(Integer, default=5)
    config: Mapped[dict] = mapped_column(Json, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        Index(
            "ix_articles_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ).ddl_if(dialect="postgresql"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text, unique=True)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, default="")
    body_kind: Mapped[str] = mapped_column(String(30), default="unknown")
    author: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    content_hash: Mapped[str | None] = mapped_column(String(16), index=True)
    embedding: Mapped[list | None] = mapped_column(Embedding)
    embedding_model: Mapped[str | None] = mapped_column(String(255))
    extra: Mapped[dict] = mapped_column("metadata", Json, default=dict)


class Observation(Base):
    """Retain provenance and latest engagement when URLs/content are deduplicated."""

    __tablename__ = "article_observations"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), index=True)
    extra: Mapped[dict] = mapped_column("metadata", Json, default=dict)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Cluster(Base):
    __tablename__ = "clusters"
    __table_args__ = (CheckConstraint("cluster_size >= 1"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(Text)
    primary_article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id"))
    cluster_size: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str | None] = mapped_column(Text)
    analysis: Mapped[dict | None] = mapped_column(Json)
    analysis_input_hash: Mapped[str | None] = mapped_column(String(64))
    significance_score: Mapped[int | None] = mapped_column(Integer)
    event_type: Mapped[str | None] = mapped_column(String(50))
    analysis_status: Mapped[str] = mapped_column(String(30), default="pending")
    analysis_error: Mapped[str | None] = mapped_column(Text)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    latest_published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ClusterArticle(Base):
    __tablename__ = "cluster_articles"
    __table_args__ = (
        UniqueConstraint("article_id"),
        Index(
            "uq_cluster_primary",
            "cluster_id",
            unique=True,
            postgresql_where=text("is_primary"),
            sqlite_where=text("is_primary"),
        ),
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clusters.id"), primary_key=True)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id"), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    similarity_score: Mapped[float] = mapped_column(Float)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="running")
    counts: Mapped[dict] = mapped_column(Json, default=dict)
    errors: Mapped[list] = mapped_column(Json, default=list)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="running")
    counts: Mapped[dict] = mapped_column(Json, default=dict)
    errors: Mapped[list] = mapped_column(Json, default=list)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0)


class AnalysisCall(Base):
    """Durable billable-attempt ledger and successful stage-output cache."""

    __tablename__ = "analysis_calls"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clusters.id"), index=True)
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    stage: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(30), default="deepseek")
    model: Mapped[str] = mapped_column(String(100))
    returned_model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="started")
    output: Mapped[dict | None] = mapped_column(Json)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[float] = mapped_column(Float)
    cost_is_upper_bound: Mapped[bool] = mapped_column(Boolean, default=True)
    pricing_version: Mapped[str] = mapped_column(String(100))
    request_id: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
