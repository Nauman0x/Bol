import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

WebhookEvent = Literal["call.completed"]


class WebhookCreate(BaseModel):
    url: str = Field(min_length=1, max_length=1000)
    events: list[WebhookEvent] = Field(default_factory=lambda: ["call.completed"], min_length=1)


class WebhookResponse(BaseModel):
    id: uuid.UUID
    url: str
    events: list[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookCreated(WebhookResponse):
    # Returned once, at creation, so the caller can store it — never
    # readable again afterward. Same pattern as ApiKeyCreated.
    secret: str
