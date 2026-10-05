import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPk


class AmbienceClip(UUIDPk, TimestampMixin, Base):
    """A user-uploaded background-ambience audio clip, org-scoped like every
    other resource. Stored as bytes in Postgres rather than object storage —
    clips are small (capped at 5MB/120s in the router) and there's no other
    blob store in this stack, so adding one for this alone isn't worth it.
    """

    __tablename__ = "ambience_clips"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(100))
    duration_sec: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)
