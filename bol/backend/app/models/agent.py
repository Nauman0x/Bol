import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPk


class Agent(UUIDPk, TimestampMixin, Base):
    __tablename__ = "agents"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # { system_prompt, greeting, greeting_mode, language, voice_id, tts_provider,
    #   llm_model, temperature, max_call_duration_sec, interruption_enabled,
    #   interruption_style, interruption_mode, interruption_min_duration,
    #   interruption_min_words, false_interruption_timeout, ack_on_interrupt,
    #   resume_style, filler_phrases, boosted_keywords, ambience,
    #   ambience_volume, thinking_sound, analysis_schema } — see
    #   app/schemas/agent.py:AgentConfig
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    # [{ name, description, url, method, params_schema }, ...] plus built-in tool toggles
    tools: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
