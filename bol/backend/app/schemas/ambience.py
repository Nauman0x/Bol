import uuid
from datetime import datetime

from pydantic import BaseModel


class AmbienceClipResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    content_type: str
    duration_sec: int
    created_at: datetime

    model_config = {"from_attributes": True}
