import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OrganizationUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}
