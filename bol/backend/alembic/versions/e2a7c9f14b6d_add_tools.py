"""add tools table and backfill inline webhook tools

Revision ID: e2a7c9f14b6d
Revises: b8e2f1a4c6d0
Create Date: 2026-08-22 00:00:00.000000

"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.sql import column, table

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e2a7c9f14b6d'
down_revision: str | Sequence[str] | None = 'b8e2f1a4c6d0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'tools',
        sa.Column('org_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('method', sa.String(length=10), nullable=False),
        sa.Column('params', sa.JSON(), nullable=False),
        sa.Column('headers', sa.JSON(), nullable=False),
        sa.Column('secrets_enc', sa.LargeBinary(), nullable=True),
        sa.Column('timeout_sec', sa.Float(), nullable=False),
        sa.Column('retry_on_failure', sa.Boolean(), nullable=False),
        sa.Column('blocking', sa.Boolean(), nullable=False),
        sa.Column('pre_tool_speech', sa.JSON(), nullable=False),
        sa.Column('response_extract', sa.JSON(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_tools_org_id_name'),
    )
    op.create_index(op.f('ix_tools_org_id'), 'tools', ['org_id'], unique=False)

    _backfill_inline_webhook_tools()


def _backfill_inline_webhook_tools() -> None:
    """Lifts every inline {"type": "webhook", ...} entry out of agents.tools
    into its own tools row, and rewrites the agent's JSON to reference it by
    id — see WebhookTool/ToolRef in app/schemas/agent.py. LLM-facing
    params_schema.properties become source="llm" params, location "query"
    for a GET tool or "body" otherwise (the same split _make_webhook_tool
    used at runtime before this migration existed)."""
    conn = op.get_bind()

    agents_t = table(
        'agents',
        column('id', sa.Uuid()),
        column('org_id', sa.Uuid()),
        column('tools', sa.JSON()),
    )
    tools_t = table(
        'tools',
        column('id', sa.Uuid()),
        column('org_id', sa.Uuid()),
        column('name', sa.String()),
        column('description', sa.Text()),
        column('is_active', sa.Boolean()),
        column('url', sa.Text()),
        column('method', sa.String()),
        column('params', sa.JSON()),
        column('headers', sa.JSON()),
        column('secrets_enc', sa.LargeBinary()),
        column('timeout_sec', sa.Float()),
        column('retry_on_failure', sa.Boolean()),
        column('blocking', sa.Boolean()),
        column('pre_tool_speech', sa.JSON()),
        column('response_extract', sa.JSON()),
    )

    rows = conn.execute(sa.select(agents_t.c.id, agents_t.c.org_id, agents_t.c.tools)).fetchall()

    for agent_id, org_id, agent_tools in rows:
        if not agent_tools:
            continue
        changed = False
        new_tools = []
        for entry in agent_tools:
            if entry.get("type") != "webhook":
                new_tools.append(entry)
                continue

            method = entry.get("method", "POST")
            location = "query" if method == "GET" else "body"
            properties = (entry.get("params_schema") or {}).get("properties", {})
            required = set((entry.get("params_schema") or {}).get("required", []))
            params = [
                {
                    "name": prop_name,
                    "location": location,
                    "type": prop.get("type", "string") if prop.get("type") in
                    ("string", "number", "integer", "boolean", "object", "array") else "string",
                    "description": prop.get("description", ""),
                    "required": prop_name in required,
                    "source": "llm",
                    "value": "",
                }
                for prop_name, prop in properties.items()
            ]

            tool_id = uuid.uuid4()
            conn.execute(
                tools_t.insert().values(
                    id=tool_id,
                    org_id=org_id,
                    name=entry.get("name", f"webhook_tool_{str(tool_id)[:8]}"),
                    description=entry.get("description", ""),
                    is_active=True,
                    url=entry.get("url", ""),
                    method=method,
                    params=params,
                    headers=[],
                    secrets_enc=None,
                    timeout_sec=10.0,
                    retry_on_failure=False,
                    blocking=True,
                    pre_tool_speech={"mode": "none", "phrase": ""},
                    response_extract=[],
                )
            )
            new_tools.append({"type": "tool_ref", "tool_id": str(tool_id), "enabled": True})
            changed = True

        if changed:
            conn.execute(
                agents_t.update().where(agents_t.c.id == agent_id).values(tools=new_tools)
            )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_tools_org_id'), table_name='tools')
    op.drop_table('tools')
