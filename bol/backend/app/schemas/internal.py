import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CallEventTypeLiteral = Literal[
    "transcript_user", "transcript_agent", "tool_call", "tool_result", "status", "error"
]


class InboundCallCreate(BaseModel):
    to_number: str
    from_number: str
    livekit_room_name: str


class InboundCallCreated(BaseModel):
    call_id: uuid.UUID
    agent_id: uuid.UUID


class CallEventIn(BaseModel):
    ts: datetime
    type: CallEventTypeLiteral
    payload: dict = Field(default_factory=dict)


class CallEventsBatchIn(BaseModel):
    events: list[CallEventIn]


class CallLatencyIn(BaseModel):
    """Mirrors worker/latency.py:LatencyCollector — stats is its summary()
    output (turn_count/stages/providers), stored verbatim as latency_stats;
    avg/p95 are pulled out separately as queryable scalar columns."""

    stats: dict = Field(default_factory=dict)
    avg_latency_ms: int | None = None
    p95_latency_ms: int | None = None


class CallCompleteIn(BaseModel):
    duration_sec: int = Field(ge=0)
    end_reason: str
    ended_at: datetime | None = None
    # All optional: a worker that crashed before resolving the pipeline
    # still needs to be able to report *something* completed.
    transport: Literal["telephony", "webrtc"] | None = None
    tts_provider: str | None = None
    llm_model: str | None = None
    latency: CallLatencyIn | None = None
    # S3 object key, set only when the worker successfully started egress
    # for this call (see worker/agent.py) — never a URL (see
    # app/services/recordings.py for why).
    recording_key: str | None = None


class KnowledgeSearchIn(BaseModel):
    org_id: uuid.UUID
    query: str = Field(min_length=1, max_length=2000)


class KnowledgeSearchOut(BaseModel):
    chunks: list[str]
