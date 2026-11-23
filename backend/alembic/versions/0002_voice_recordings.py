"""add voice recording collection tables

Revision ID: 0002
Revises: 0001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voice_sessions",
        sa.Column("speaker_id", sa.String(8), primary_key=True),
        sa.Column("consent", sa.Boolean(), nullable=False),
        sa.Column("gender", sa.String(30), nullable=False),
        sa.Column("age_band", sa.String(30), nullable=False),
        sa.Column("region", sa.String(255), nullable=False),
        sa.Column("mother_tongue", sa.String(100), nullable=True),
        sa.Column("device", sa.String(100), nullable=True),
        sa.Column("environment", sa.String(100), nullable=False),
        sa.Column("script", sa.String(20), nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "voice_clips",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("speaker_id", sa.String(8), sa.ForeignKey("voice_sessions.speaker_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sentence_id", sa.String(100), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("speaker_id", "sentence_id", name="uq_voice_clip_speaker_sentence"),
    )
    op.create_index("ix_voice_clips_speaker_id", "voice_clips", ["speaker_id"])
    op.create_index("ix_voice_clips_sentence_id", "voice_clips", ["sentence_id"])


def downgrade() -> None:
    op.drop_index("ix_voice_clips_sentence_id", table_name="voice_clips")
    op.drop_index("ix_voice_clips_speaker_id", table_name="voice_clips")
    op.drop_table("voice_clips")
    op.drop_table("voice_sessions")
