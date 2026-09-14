"""Add Supabase-backed profiles and per-user topic preferences."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0003_dashboard_users"
down_revision = "0002_cluster_analysis"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("subscription_tier", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("subscription_tier IN ('free', 'pro')"),
    )
    op.create_table(
        "user_topics",
        sa.Column(
            "user_id", UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("topic", sa.String(60), primary_key=True),
    )


def downgrade():
    op.drop_table("user_topics")
    op.drop_table("users")
