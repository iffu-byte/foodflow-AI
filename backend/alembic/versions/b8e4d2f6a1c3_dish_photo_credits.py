"""dish and restaurant photo credits

Revision ID: b8e4d2f6a1c3
Revises: a7d3c9e1f2b4
Create Date: 2026-11-14 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8e4d2f6a1c3"
down_revision: str | None = "a7d3c9e1f2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("restaurants", "menu_items"):
        op.add_column(
            table,
            sa.Column(
                "image_credit",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    for table in ("menu_items", "restaurants"):
        op.drop_column(table, "image_credit")
