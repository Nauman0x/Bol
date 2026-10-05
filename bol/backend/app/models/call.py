import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, LargeBinary, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPk


class CallDirection(enum.StrEnum):
    inbound = "inbound"
    outbound = "outbound"
    # Browser test calls (POST /agents/{id}/test-session) used to have no Call
    # row at all (call_id=None), which meant their latency/transcript data
    # was silently discarded — EventReporter no-ops without a call_id. They
    # now get a real row like any other call so latency is comparable across
    # every transport, not just telephony.
    test = "test"


class CallStatus(enum.StrEnum):
    queued = "queued"
    ringing = "ringing"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    no_answer = "no_answer"
    busy = "busy"


class Call(UUIDPk, TimestampMixin, Base):
    __tablename__ = "calls"
    __table_args__ = (
        # GET /calls and the analytics endpoints both filter on org_id and
        # sort/range on created_at (routers/calls.py, routers/analytics.py)
        # — without this they fall back to the single-column org_id index
        # plus a full sort/scan of that org's rows.
        Index("ix_calls_org_id_created_at", "org_id", "created_at"),
        # The platform-wide per-provider concurrency check
        # (routers/calls.py:_check_provider_concurrency) filters on status
        # + tts_provider across *all* orgs — without this it's a full table
        # scan of `calls` on every single outbound call and test session.
        Index("ix_calls_status_tts_provider", "status", "tts_provider"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"), index=True)
    phone_number_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("phone_numbers.id"), nullable=True
    )
    direction: Mapped[CallDirection] = mapped_column(Enum(CallDirection, name="call_direction"))
    to_number: Mapped[str] = mapped_column(String(20))
    from_number: Mapped[str] = mapped_column(String(20))
    status: Mapped[CallStatus] = mapped_column(
        Enum(CallStatus, name="call_status"), default=CallStatus.queued, index=True
    )
    livekit_room_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # S3 object key for this call's recording, not a URL — playback URLs are
    # presigned on demand (app/services/recordings.py), never stored.
    recording_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Local fallback for when no S3 bucket is configured — the worker's own
    # RecorderIO capture (worker/agent.py) uploaded straight to this row
    # instead of via egress+S3. Mutually exclusive with recording_key in
    # practice, never both: whichever recording path ran for this call.
    recording_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    recording_content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cost_estimate: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    # Post-call LLM analysis (app/services/call_analysis.py): summary/outcome/
    # sentiment plus any per-agent custom extraction fields. None until the
    # call reaches a terminal state and analysis succeeds — best-effort, a
    # failed analysis just leaves this null rather than blocking completion.
    analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Latency: full per-stage breakdown (worker/latency.py:LatencyCollector.summary())
    # plus two scalar columns pulled out of it so simple filters/sorts ("calls over
    # 2s") don't need JSON extraction — SQLite (tests) and Postgres (prod) don't
    # share JSON query syntax, so keeping the hot-path numbers as real columns
    # avoids that split entirely. transport/tts_provider/llm_model are the
    # dimensions the latency analytics endpoint groups by.
    latency_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    avg_latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    p95_latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    transport: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tts_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    events: Mapped[list["CallEvent"]] = relationship(
        back_populates="call", order_by="CallEvent.ts"
    )


class CallEventType(enum.StrEnum):
    transcript_user = "transcript_user"
    transcript_agent = "transcript_agent"
    tool_call = "tool_call"
    tool_result = "tool_result"
    status = "status"
    error = "error"


class CallEvent(UUIDPk, Base):
    __tablename__ = "call_events"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    type: Mapped[CallEventType] = mapped_column(Enum(CallEventType, name="call_event_type"))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    call: Mapped["Call"] = relationship(back_populates="events")
