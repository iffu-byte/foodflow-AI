"""rider live gps metadata

Revision ID: 8b7d2f31c9a4
Revises: fc4f166daaf6
Create Date: 2026-11-11 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "8b7d2f31c9a4"
down_revision: str | None = "fc4f166daaf6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "riders",
        sa.Column(
            "location_source",
            sa.String(length=16),
            nullable=False,
            server_default="simulated",
        ),
    )
    op.add_column(
        "riders",
        sa.Column("location_accuracy_m", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("riders", "location_accuracy_m")
    op.drop_column("riders", "location_source")
