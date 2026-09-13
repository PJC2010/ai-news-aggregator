"""Persist shared analysis status, stage caches, usage, and run history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0002_cluster_analysis"
down_revision = "0001_pipeline_core"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "articles", sa.Column("body_kind", sa.String(30), nullable=False, server_default="unknown")
    )
    op.alter_column("articles", "body_kind", server_default=None)
    op.add_column(
        "clusters",
        sa.Column("analysis_status", sa.String(30), nullable=False, server_default="pending"),
    )
    op.add_column("clusters", sa.Column("analysis_error", sa.Text()))
    op.add_column("clusters", sa.Column("analyzed_at", sa.DateTime(timezone=True)))
    op.alter_column("clusters", "analysis_status", server_default=None)
    op.create_table(
        "analysis_runs",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("counts", JSONB(), nullable=False),
        sa.Column("errors", JSONB(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
    )
    op.create_table(
        "analysis_calls",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("run_id", UUID(), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("cluster_id", UUID(), sa.ForeignKey("clusters.id"), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("returned_model", sa.String(100)),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("output", JSONB()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("cached_input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column("cost_is_upper_bound", sa.Boolean(), nullable=False),
        sa.Column("pricing_version", sa.String(100), nullable=False),
        sa.Column("request_id", sa.String(255)),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    for column in ("run_id", "cluster_id", "cache_key"):
        op.create_index(f"ix_analysis_calls_{column}", "analysis_calls", [column])


def downgrade():
    op.drop_table("analysis_calls")
    op.drop_table("analysis_runs")
    op.drop_column("clusters", "analyzed_at")
    op.drop_column("clusters", "analysis_error")
    op.drop_column("clusters", "analysis_status")
    op.drop_column("articles", "body_kind")
