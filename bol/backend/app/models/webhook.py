import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPk


class Webhook(UUIDPk, TimestampMixin, Base):
    __tablename__ = "webhooks"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    # HMAC-SHA256 signing key for the X-BOL-Signature header — generated
    # server-side at creation, returned to the caller once (see
    # WebhookCreated), never re-readable afterward, same pattern as ApiKey.
    secret: Mapped[str] = mapped_column(String(100))
    events: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
