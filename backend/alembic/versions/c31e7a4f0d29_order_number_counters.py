"""atomic marketplace order numbers

Revision ID: c31e7a4f0d29
Revises: 8b7d2f31c9a4
Create Date: 2026-11-12 21:15:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c31e7a4f0d29"
down_revision: str | None = "8b7d2f31c9a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "order_number_counters",
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("next_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("year"),
    )
    op.execute(
        """
        INSERT INTO order_number_counters (year, next_value)
        SELECT
            substring(order_number FROM '^FF-([0-9]{4})-')::integer,
            max(substring(order_number FROM '-([0-9]+)$')::integer)
        FROM orders
        WHERE order_number ~ '^FF-[0-9]{4}-[0-9]+$'
        GROUP BY substring(order_number FROM '^FF-([0-9]{4})-')::integer
        """
    )


def downgrade() -> None:
    op.drop_table("order_number_counters")
