import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PhoneNumberProvider = Literal["telnyx", "twilio"]


class PhoneNumberCreate(BaseModel):
    e164: str = Field(pattern=r"^\+[1-9]\d{1,14}$")
    provider: PhoneNumberProvider = "telnyx"
    livekit_trunk_id: str | None = None
    inbound_agent_id: uuid.UUID | None = None


class PhoneNumberUpdate(BaseModel):
    inbound_agent_id: uuid.UUID | None = None
    livekit_trunk_id: str | None = None


class PhoneNumberResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    e164: str
    provider: str
    livekit_trunk_id: str | None
    inbound_agent_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
