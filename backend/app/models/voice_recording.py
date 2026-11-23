import secrets
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def generate_speaker_id() -> str:
    return secrets.token_hex(4)


class VoiceSession(Base):
    __tablename__ = "voice_sessions"

    speaker_id: Mapped[str] = mapped_column(String(8), primary_key=True, default=generate_speaker_id)
    consent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    gender: Mapped[str] = mapped_column(String(30), nullable=False)
    age_band: Mapped[str] = mapped_column(String(30), nullable=False)
    region: Mapped[str] = mapped_column(String(255), nullable=False)
    mother_tongue: Mapped[str | None] = mapped_column(String(100), nullable=True)
    device: Mapped[str | None] = mapped_column(String(100), nullable=True)
    environment: Mapped[str] = mapped_column(String(100), nullable=False)
    script: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    clips: Mapped[list["VoiceClip"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class VoiceClip(Base):
    __tablename__ = "voice_clips"
    __table_args__ = (UniqueConstraint("speaker_id", "sentence_id", name="uq_voice_clip_speaker_sentence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    speaker_id: Mapped[str] = mapped_column(
        String(8), ForeignKey("voice_sessions.speaker_id", ondelete="CASCADE"), nullable=False, index=True
    )
    sentence_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[VoiceSession] = relationship(back_populates="clips")
