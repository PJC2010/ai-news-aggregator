"""Pipeline core: raw articles, provenance, semantic events, and run status."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001_pipeline_core"
down_revision = None
branch_labels = None
depends_on = None


def identifier():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def timestamp(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "sources",
        identifier(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("authority_score", sa.Integer(), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        timestamp("last_fetched_at", True),
        sa.Column("last_error", sa.Text()),
        timestamp("created_at"),
        sa.CheckConstraint("authority_score BETWEEN 1 AND 10"),
    )
    op.create_table(
        "articles",
        identifier(),
        sa.Column("source_id", UUID(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False, unique=True),
        sa.Column("url_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author", sa.Text()),
        timestamp("published_at", True),
        timestamp("fetched_at"),
        sa.Column("content_hash", sa.String(16)),
        sa.Column("embedding", Vector(384)),
        sa.Column("embedding_model", sa.String(255)),
        sa.Column("metadata", JSONB(), nullable=False),
    )
    op.create_index("ix_articles_published_at", "articles", ["published_at"])
    op.create_index("ix_articles_content_hash", "articles", ["content_hash"])
    op.create_index("ix_articles_source_id", "articles", ["source_id"])
    # HNSW can be created before ingestion. IVFFlat needs representative training data.
    op.create_index(
        "ix_articles_embedding",
        "articles",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "article_observations",
        identifier(),
        sa.Column("article_id", UUID(), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("source_id", UUID(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False),
        timestamp("seen_at"),
        sa.UniqueConstraint("source_id", "external_id"),
    )
    op.create_index("ix_article_observations_article_id", "article_observations", ["article_id"])
    op.create_index("ix_article_observations_url_hash", "article_observations", ["url_hash"])
    op.create_table(
        "clusters",
        identifier(),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("primary_article_id", UUID(), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("cluster_size", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("analysis", JSONB()),
        sa.Column("analysis_input_hash", sa.String(64)),
        sa.Column("significance_score", sa.Integer()),
        sa.Column("event_type", sa.String(50)),
        timestamp("created_at"),
        timestamp("updated_at"),
        timestamp("latest_published_at"),
        sa.CheckConstraint("cluster_size >= 1"),
    )
    op.create_index("ix_clusters_latest_published_at", "clusters", ["latest_published_at"])
    op.create_table(
        "cluster_articles",
        sa.Column("cluster_id", UUID(), sa.ForeignKey("clusters.id"), primary_key=True),
        sa.Column("article_id", UUID(), sa.ForeignKey("articles.id"), primary_key=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.UniqueConstraint("article_id"),
    )
    op.create_index(
        "uq_cluster_primary",
        "cluster_articles",
        ["cluster_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )
    op.create_table(
        "pipeline_runs",
        identifier(),
        timestamp("started_at"),
        timestamp("finished_at", True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("counts", JSONB(), nullable=False),
        sa.Column("errors", JSONB(), nullable=False),
    )


def downgrade():
    for table in [
        "pipeline_runs",
        "cluster_articles",
        "clusters",
        "article_observations",
        "articles",
        "sources",
    ]:
        op.drop_table(table)
    # The extension may be shared with other applications; do not remove it.
