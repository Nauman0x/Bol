"""add call recording blob columns

Revision ID: 714ede81564f
Revises: e2a7c9f14b6d
Create Date: 2026-09-20 13:49:25.093754

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '714ede81564f'
down_revision: Union[str, Sequence[str], None] = 'e2a7c9f14b6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("calls", sa.Column("recording_data", sa.LargeBinary(), nullable=True))
    op.add_column(
        "calls", sa.Column("recording_content_type", sa.String(length=100), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("calls", "recording_content_type")
    op.drop_column("calls", "recording_data")
