"""model versions

Revision ID: b7c1e4f92a10
Revises: 9052d861b47c
Create Date: 2026-11-10 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'b7c1e4f92a10'
down_revision: str | None = '9052d861b47c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'model_versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=40), nullable=False),
        sa.Column('version', sa.String(length=80), nullable=False),
        sa.Column('artifact_path', sa.String(length=255), nullable=True),
        sa.Column('row_count', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('version'),
    )
    op.create_index(
        'ix_model_versions_created_at', 'model_versions', ['created_at'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_model_versions_created_at', table_name='model_versions')
    op.drop_table('model_versions')
