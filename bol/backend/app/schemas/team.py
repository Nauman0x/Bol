import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole


class TeamMemberInvite(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    role: UserRole = UserRole.member


class TeamMemberInvited(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: UserRole
    temp_password: str


class TeamMemberResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: UserRole
    created_at: datetime

    model_config = {"from_attributes": True}
