import uuid
from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from app.models.call import CallDirection, CallEventType, CallStatus


class OutboundCallCreate(BaseModel):
    agent_id: uuid.UUID
    to_number: str = Field(pattern=r"^\+[1-9]\d{1,14}$")
    phone_number_id: uuid.UUID | None = None


class CallResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    agent_id: uuid.UUID
    phone_number_id: uuid.UUID | None
    direction: CallDirection
    to_number: str
    from_number: str
    status: CallStatus
    livekit_room_name: str | None
    started_at: datetime | None
    answered_at: datetime | None
    ended_at: datetime | None
    duration_sec: int | None
    end_reason: str | None
    # Internal S3 object key — excluded from the serialized response.
    # Playback goes through GET /calls/{id}/recording, which presigns a
    # short-lived URL on demand (app/services/recordings.py) rather than
    # exposing the key or a permanent URL.
    recording_key: str | None = Field(exclude=True)
    # Excluded like recording_key above — never serialize recording_data
    # itself (it isn't even declared as a field here), just whether one
    # exists, same as the S3 path's recording_key check.
    recording_content_type: str | None = Field(exclude=True, default=None)
    transport: str | None
    tts_provider: str | None
    llm_model: str | None
    avg_latency_ms: int | None
    p95_latency_ms: int | None
    cost_estimate: float | None
    created_at: datetime

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def has_recording(self) -> bool:
        return self.recording_key is not None or self.recording_content_type is not None


class CallEventResponse(BaseModel):
    id: uuid.UUID
    call_id: uuid.UUID
    ts: datetime
    type: CallEventType
    payload: dict

    model_config = {"from_attributes": True}


class CallDetailResponse(CallResponse):
    events: list[CallEventResponse]
    latency_stats: dict | None
    analysis: dict | None


class ListenSessionResponse(BaseModel):
    livekit_url: str
    room_name: str
    token: str


class RecordingUrlResponse(BaseModel):
    url: str
