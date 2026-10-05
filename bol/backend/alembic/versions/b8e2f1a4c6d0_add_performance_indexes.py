"""add performance indexes: api_keys.prefix, calls composite indexes

Revision ID: b8e2f1a4c6d0
Revises: c7d3e0a5f918
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b8e2f1a4c6d0'
down_revision: Union[str, Sequence[str], None] = 'c7d3e0a5f918'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Narrows candidates before the bcrypt verify in
    # app/security.py:_authenticate_api_key — every authenticated API-key
    # request was a full table scan without this.
    op.create_index(op.f('ix_api_keys_prefix'), 'api_keys', ['prefix'], unique=False)

    # GET /calls and the analytics endpoints filter on org_id and sort/range
    # on created_at together (routers/calls.py, routers/analytics.py).
    op.create_index('ix_calls_org_id_created_at', 'calls', ['org_id', 'created_at'], unique=False)

    # The platform-wide per-provider concurrency check
    # (routers/calls.py:_check_provider_concurrency) filters on status +
    # tts_provider across every org — a full table scan on `calls` without
    # this, on every outbound call and test session.
    op.create_index(
        'ix_calls_status_tts_provider', 'calls', ['status', 'tts_provider'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_calls_status_tts_provider', table_name='calls')
    op.drop_index('ix_calls_org_id_created_at', table_name='calls')
    op.drop_index(op.f('ix_api_keys_prefix'), table_name='api_keys')
