import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ApiKeyCreated(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    created_at: datetime
    # Returned exactly once, at creation — only the hash is stored.
    key: str


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}
