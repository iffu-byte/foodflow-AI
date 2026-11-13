"""payment gateway audit records

Revision ID: e6a4f91b2d77
Revises: c31e7a4f0d29
Create Date: 2026-11-12 22:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "e6a4f91b2d77"
down_revision: str | None = "c31e7a4f0d29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("provider_order_id", sa.String(length=100), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=100), nullable=True),
        sa.Column("signature_verified", sa.Boolean(), nullable=False),
        sa.Column("provider_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "provider", name="uq_payment_attempt_order_provider"),
        sa.UniqueConstraint("provider", "provider_order_id", name="uq_payment_provider_order"),
        sa.UniqueConstraint("provider", "provider_payment_id", name="uq_payment_provider_payment"),
    )
    op.create_index(
        "ix_payment_attempts_provider_order",
        "payment_attempts",
        ["provider", "provider_order_id"],
        unique=False,
    )
    op.create_table(
        "payment_webhook_receipts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_payment_webhook_event"),
    )


def downgrade() -> None:
    op.drop_table("payment_webhook_receipts")
    op.drop_index("ix_payment_attempts_provider_order", table_name="payment_attempts")
    op.drop_table("payment_attempts")
