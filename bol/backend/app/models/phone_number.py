import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPk


class PhoneNumber(UUIDPk, TimestampMixin, Base):
    __tablename__ = "phone_numbers"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    e164: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(50), default="telnyx")
    livekit_trunk_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    inbound_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
