from pydantic import BaseModel, Field


class VoiceSessionCreate(BaseModel):
    consent: bool
    gender: str = Field(min_length=1)
    age_band: str = Field(min_length=1)
    region: str = Field(min_length=1)
    mother_tongue: str | None = None
    device: str | None = None
    environment: str = Field(min_length=1)
    script: str | None = None


class VoiceSessionCreateResponse(BaseModel):
    speakerId: str


class VoiceProgressResponse(BaseModel):
    done: list[str]
