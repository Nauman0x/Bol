import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPk


class Tool(UUIDPk, TimestampMixin, Base):
    """An org-level, reusable webhook tool an agent can call mid-call. See
    app/schemas/tool.py for the full shape of params/headers/response_extract
    and app/services/tool_executor.py for how they're resolved and called.
    """

    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_tools_org_id_name"),)

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    # The LLM-visible function name — must be a valid function-tool identifier.
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    url: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(10), default="POST")
    # list[ToolParam] — see app/schemas/tool.py
    params: Mapped[list] = mapped_column(JSON, default=list)
    # list[{name, value_type: "literal"|"secret", value?, secret_ref?}]
    headers: Mapped[list] = mapped_column(JSON, default=list)
    # Fernet-encrypted {secret_ref: plaintext} blob, see app/services/crypto.py.
    # Never returned to the dashboard — only decrypted on the
    # /internal/agents/{id}/tools path the worker calls.
    secrets_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    timeout_sec: Mapped[float] = mapped_column(Float, default=10.0)
    retry_on_failure: Mapped[bool] = mapped_column(Boolean, default=True)
    # False = fire-and-forget: the tool call runs in the background and the
    # turn continues immediately instead of waiting on the response.
    blocking: Mapped[bool] = mapped_column(Boolean, default=True)
    # {mode: "none"|"fixed"|"auto", phrase: str}
    pre_tool_speech: Mapped[dict] = mapped_column(JSON, default=dict)
    # list[{name, path, description}] — dotted-path extraction from a JSON
    # response; empty means "return raw truncated text" (see tool_executor.py).
    response_extract: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
