import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeDocumentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Plain text/markdown only for now — no PDF/DOCX parsing.
    content: str = Field(min_length=1, max_length=200_000)


class KnowledgeDocumentResponse(BaseModel):
    id: uuid.UUID
    name: str
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}
