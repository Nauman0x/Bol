"""add call latency columns

Revision ID: d476c21e9827
Revises: 4d3674168b72
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd476c21e9827'
down_revision: Union[str, Sequence[str], None] = '4d3674168b72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Postgres enums are closed sets — "test" (browser test calls, which
    # previously had no Call row at all) needs to be added explicitly.
    # Safe on Postgres 12+ (this project targets postgres:16 — see
    # docker-compose.yml) to run inside a transaction; no-op on SQLite,
    # which has no native enum type to alter.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE call_direction ADD VALUE IF NOT EXISTS 'test'")

    op.add_column('calls', sa.Column('latency_stats', sa.JSON(), nullable=True))
    op.add_column('calls', sa.Column('avg_latency_ms', sa.Integer(), nullable=True))
    op.add_column('calls', sa.Column('p95_latency_ms', sa.Integer(), nullable=True))
    op.add_column('calls', sa.Column('transport', sa.String(length=20), nullable=True))
    op.add_column('calls', sa.Column('tts_provider', sa.String(length=50), nullable=True))
    op.add_column('calls', sa.Column('llm_model', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('calls', 'llm_model')
    op.drop_column('calls', 'tts_provider')
    op.drop_column('calls', 'transport')
    op.drop_column('calls', 'p95_latency_ms')
    op.drop_column('calls', 'avg_latency_ms')
    op.drop_column('calls', 'latency_stats')
