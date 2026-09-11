import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentConfig(BaseModel):
    system_prompt: str = Field(min_length=1, max_length=8000)
    greeting: str = Field(min_length=1, max_length=1000)
    language: Literal["en", "ur", "auto"] = "auto"
    voice_id: str = Field(min_length=1, max_length=100)
    llm_model: str = Field(min_length=1, max_length=100)
    temperature: float = Field(ge=0.0, le=2.0, default=0.7)
    max_call_duration_sec: int = Field(ge=30, le=3600, default=300)


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    config: AgentConfig


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    config: AgentConfig | None = None


class AgentResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    config: AgentConfig
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Voice(BaseModel):
    id: str
    label: str
    language: str


class TestSessionResponse(BaseModel):
    call_id: uuid.UUID
    room_name: str
    livekit_url: str
    token: str
