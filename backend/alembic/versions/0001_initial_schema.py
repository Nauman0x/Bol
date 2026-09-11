"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("org_id", sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("org_id", sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("config", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agents_org_id", "agents", ["org_id"])

    op.create_table(
        "calls",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("org_id", sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("agent_id", sa.Uuid(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False, server_default="test"),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_progress"),
        sa.Column("livekit_room_name", sa.String(255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_sec", sa.Integer, nullable=True),
        sa.Column("end_reason", sa.String(50), nullable=True),
    )
    op.create_index("ix_calls_org_id", "calls", ["org_id"])
    op.create_index("ix_calls_agent_id", "calls", ["agent_id"])

    op.create_table(
        "call_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("call_id", sa.Uuid(as_uuid=True), sa.ForeignKey("calls.id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False, server_default="{}"),
    )
    op.create_index("ix_call_events_call_id", "call_events", ["call_id"])


def downgrade() -> None:
    op.drop_table("call_events")
    op.drop_table("calls")
    op.drop_table("agents")
    op.drop_table("users")
    op.drop_table("organizations")
