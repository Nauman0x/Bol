"""rename calls.recording_url to recording_key

Revision ID: f4b1c9a6e2d7
Revises: a1e9f7c3d8b2
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4b1c9a6e2d7'
down_revision: Union[str, Sequence[str], None] = 'a1e9f7c3d8b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # The column now stores an S3 object key, not a URL — playback URLs are
    # presigned on demand (app/services/recordings.py), never persisted.
    op.alter_column('calls', 'recording_url', new_column_name='recording_key')


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('calls', 'recording_key', new_column_name='recording_url')
