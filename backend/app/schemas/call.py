import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class CallResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    agent_id: uuid.UUID
    direction: str
    status: str
    livekit_room_name: str
    started_at: datetime
    ended_at: datetime | None
    duration_sec: int | None
    end_reason: str | None

    model_config = ConfigDict(from_attributes=True)


class CallEventResponse(BaseModel):
    id: uuid.UUID
    call_id: uuid.UUID
    ts: datetime
    type: str
    payload: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class CallEventCreate(BaseModel):
    type: str
    payload: dict[str, Any] = {}


class CallCompleteRequest(BaseModel):
    duration_sec: int
    end_reason: str
