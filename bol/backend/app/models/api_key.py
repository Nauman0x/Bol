import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPk


class ApiKey(UUIDPk, TimestampMixin, Base):
    __tablename__ = "api_keys"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    key_hash: Mapped[str] = mapped_column(String(200))
    # Narrows candidates before the bcrypt verify in
    # app/security.py:_authenticate_api_key — without an index that lookup
    # is a full table scan on every single authenticated API-key request.
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
