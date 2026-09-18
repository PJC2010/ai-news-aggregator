"""Add minimal Stripe reconciliation state and webhook receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0004_stripe_billing"
down_revision = "0003_dashboard_users"
branch_labels = None
depends_on = None


def upgrade():
    for name, column in (
        ("stripe_customer_id", sa.String(255)),
        ("stripe_subscription_id", sa.String(255)),
        ("stripe_subscription_status", sa.String(30)),
        ("stripe_price_id", sa.String(255)),
        ("entitlement_expires_at", sa.DateTime(timezone=True)),
        ("stripe_state_created_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("users", sa.Column(name, column, nullable=True))
    op.create_unique_constraint("uq_users_stripe_customer_id", "users", ["stripe_customer_id"])
    op.create_unique_constraint("uq_users_stripe_subscription_id", "users", ["stripe_subscription_id"])
    op.create_table(
        "stripe_events",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("stripe_events")
    op.drop_constraint("uq_users_stripe_subscription_id", "users", type_="unique")
    op.drop_constraint("uq_users_stripe_customer_id", "users", type_="unique")
    for name in (
        "stripe_state_created_at", "entitlement_expires_at", "stripe_price_id",
        "stripe_subscription_status", "stripe_subscription_id", "stripe_customer_id",
    ):
        op.drop_column("users", name)
