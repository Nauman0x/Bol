"""Endpoints called by the worker process, never by the frontend.

Auth is a single shared bearer token (INTERNAL_SERVICE_TOKEN), not a user session —
the worker holds no user/org context, only the call_id and agent_id from job metadata.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_db, get_session_factory
from app.models.agent import Agent
from app.models.ambience_clip import AmbienceClip
from app.models.call import Call, CallDirection, CallEvent, CallStatus
from app.models.phone_number import PhoneNumber
from app.models.tool import Tool
from app.models.webhook import Webhook
from app.schemas.agent import AgentResponse
from app.schemas.internal import (
    CallCompleteIn,
    CallEventsBatchIn,
    InboundCallCreate,
    InboundCallCreated,
    KnowledgeSearchIn,
    KnowledgeSearchOut,
)
from app.schemas.tool import ToolResolved
from app.security import InternalAuth
from app.services import knowledge
from app.services.call_analysis import analyze_call
from app.services.cost import estimate_cost
from app.services.crypto import decrypt_secrets
from app.services.webhook_dispatch import dispatch as dispatch_webhooks

logger = logging.getLogger("BOL.internal")

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[InternalAuth])

_TERMINAL_STATUSES = (
    CallStatus.completed,
    CallStatus.failed,
    CallStatus.no_answer,
    CallStatus.busy,
)

# end_reason values that mean the call never really connected / didn't end
# normally — everything else maps to "completed". Keeping this as an
# explicit map (not a Literal on CallCompleteIn.end_reason) because
# on_end_call/max_duration/etc paths in the worker are free-form strings
# today and constraining them is a separate change.
_END_REASON_TO_STATUS = {
    "no_answer": CallStatus.no_answer,
    "busy": CallStatus.busy,
    "dispatch_failed": CallStatus.failed,
    "agent_config_fetch_failed": CallStatus.failed,
    "tts_init_failed": CallStatus.failed,
    "pipeline_error": CallStatus.failed,
    "worker_lost": CallStatus.failed,
}


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent_for_worker(
    agent_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


@router.get("/ambience/{clip_id}")
async def get_ambience_clip_for_worker(
    clip_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> Response:
    """Raw clip bytes for the worker's BackgroundAudioPlayer. Not org-scoped
    (the worker has no user/org context, only the clip id from an agent's
    config) — that's fine, a clip id is an unguessable UUID."""
    result = await db.execute(select(AmbienceClip).where(AmbienceClip.id == clip_id))
    clip = result.scalar_one_or_none()
    if clip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ambience clip not found")
    return Response(content=clip.data, media_type=clip.content_type)


@router.post(
    "/calls/inbound", response_model=InboundCallCreated, status_code=status.HTTP_201_CREATED
)
async def create_inbound_call(
    payload: InboundCallCreate, db: Annotated[AsyncSession, Depends(get_db)]
) -> InboundCallCreated:
    """Called by the worker when it picks up a job with no agent_id in its
    dispatch metadata — the signal that this is an inbound SIP call, not one
    BOL dispatched itself. Resolves the called DID to its org + inbound
    agent and creates the call row that outbound calls get from /calls/outbound.
    """
    result = await db.execute(select(PhoneNumber).where(PhoneNumber.e164 == payload.to_number))
    number = result.scalar_one_or_none()
    if number is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown phone number")
    if number.inbound_agent_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Phone number has no inbound agent assigned",
        )

    call = Call(
        org_id=number.org_id,
        agent_id=number.inbound_agent_id,
        phone_number_id=number.id,
        direction=CallDirection.inbound,
        to_number=payload.to_number,
        from_number=payload.from_number,
        status=CallStatus.in_progress,
        livekit_room_name=payload.livekit_room_name,
        started_at=datetime.now(UTC),
        answered_at=datetime.now(UTC),
        transport="telephony",
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return InboundCallCreated(call_id=call.id, agent_id=call.agent_id)


@router.get("/agents/{agent_id}/tools", response_model=list[ToolResolved])
async def get_agent_tools_for_worker(
    agent_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[ToolResolved]:
    """Resolved (secrets decrypted) Tool rows for this agent's tool_ref
    entries — kept as its own internal-only endpoint, never folded into
    AgentResponse, so a decrypted header value can never reach a
    dashboard-facing response (see app/schemas/tool.py:ToolResolved)."""
    agent_result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = agent_result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    tool_ids = [
        uuid.UUID(entry["tool_id"])
        for entry in agent.tools
        if entry.get("type") == "tool_ref" and entry.get("enabled", True)
    ]
    if not tool_ids:
        return []

    result = await db.execute(select(Tool).where(Tool.id.in_(tool_ids), Tool.is_active.is_(True)))
    resolved = []
    for tool in result.scalars().all():
        secrets = decrypt_secrets(tool.secrets_enc)
        resolved_headers = {
            h["name"]: (
                secrets.get(h.get("secret_ref"), "")
                if h["value_type"] == "secret"
                else h["value"]
            )
            for h in tool.headers
        }
        resolved.append(
            ToolResolved(
                id=tool.id,
                name=tool.name,
                description=tool.description,
                is_active=tool.is_active,
                url=tool.url,
                method=tool.method,
                params=tool.params,
                headers=tool.headers,
                timeout_sec=tool.timeout_sec,
                retry_on_failure=tool.retry_on_failure,
                blocking=tool.blocking,
                pre_tool_speech=tool.pre_tool_speech,
                response_extract=tool.response_extract,
                resolved_headers=resolved_headers,
            )
        )
    return resolved


@router.post("/knowledge/search", response_model=KnowledgeSearchOut)
async def search_knowledge_for_worker(
    payload: KnowledgeSearchIn, db: Annotated[AsyncSession, Depends(get_db)]
) -> KnowledgeSearchOut:
    """Backs the `lookup_knowledge` agent tool (worker/tools.py) — the
    worker never touches the DB or the embedding model directly, same as
    every other internal endpoint."""
    chunks = await knowledge.search(db, payload.org_id, payload.query)
    return KnowledgeSearchOut(chunks=chunks)


@router.post("/calls/{call_id}/answered", status_code=status.HTTP_204_NO_CONTENT)
async def mark_call_answered(
    call_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    """Called by the worker once a call is actually connected: for outbound
    telephony, after sip.callStatus flips to "active" (see
    worker/agent.py:_wait_until_answered); for webrtc test calls, right
    before session.start() since there's no ring phase. Inbound calls skip
    this — they're marked in_progress/answered_at directly at row creation
    in create_inbound_call below, since by the time our job even starts the
    SIP leg has already been accepted."""
    result = await db.execute(select(Call).where(Call.id == call_id))
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    call.status = CallStatus.in_progress
    call.answered_at = datetime.now(UTC)
    await db.commit()


@router.post("/calls/{call_id}/events", status_code=status.HTTP_204_NO_CONTENT)
async def report_call_events(
    call_id: uuid.UUID,
    payload: CallEventsBatchIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(select(Call.id).where(Call.id == call_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    for event in payload.events:
        db.add(CallEvent(call_id=call_id, ts=event.ts, type=event.type, payload=event.payload))
    await db.commit()


async def _finalize_call_side_effects(
    call_id: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Runs after the /complete response has already been sent to the
    worker. Post-call analysis is an LLM round-trip and webhook delivery is
    one or more outbound HTTP calls — neither should make the worker's
    shutdown wait on this endpoint (worker/agent.py's _cleanup shutdown
    callback awaits complete_call before the job process exits). Best-effort
    throughout: any failure here is logged, never raised, since nothing
    downstream is waiting on it."""
    async with session_factory() as db:
        result = await db.execute(select(Call).where(Call.id == call_id))
        call = result.scalar_one_or_none()
        if call is None:
            return

        events_result = await db.execute(
            select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.ts)
        )
        events = [
            {"type": event.type.value, "payload": event.payload}
            for event in events_result.scalars().all()
        ]

        agent_result = await db.execute(select(Agent).where(Agent.id == call.agent_id))
        agent = agent_result.scalar_one_or_none()
        analysis_schema = (agent.config or {}).get("analysis_schema", {}) if agent else {}

        analysis = await analyze_call(events, analysis_schema)
        if analysis is not None:
            call.analysis = analysis
            await db.commit()

        webhooks_result = await db.execute(
            select(Webhook).where(Webhook.org_id == call.org_id, Webhook.is_active.is_(True))
        )
        subscribers = [
            (webhook.url, webhook.secret)
            for webhook in webhooks_result.scalars().all()
            if "call.completed" in webhook.events
        ]
        try:
            await dispatch_webhooks(
                subscribers,
                "call.completed",
                {
                    "call_id": str(call.id),
                    "agent_id": str(call.agent_id),
                    "direction": call.direction.value,
                    "status": call.status.value,
                    "to_number": call.to_number,
                    "from_number": call.from_number,
                    "duration_sec": call.duration_sec,
                    "end_reason": call.end_reason,
                    "cost_estimate": call.cost_estimate,
                    "analysis": call.analysis,
                },
            )
        except Exception:
            logger.exception("Webhook dispatch failed for call %s", call_id)


_MAX_RECORDING_BYTES = 100 * 1024 * 1024  # a 2hr call at opus voice bitrates is well under this


@router.put("/calls/{call_id}/recording", status_code=status.HTTP_204_NO_CONTENT)
async def upload_call_recording(
    call_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Raw audio bytes from the worker's local RecorderIO capture
    (worker/agent.py) — the fallback recording path used when no S3 bucket
    is configured. See app/models/call.py:recording_data."""
    body = await request.body()
    if len(body) > _MAX_RECORDING_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Recording too large"
        )
    result = await db.execute(select(Call).where(Call.id == call_id))
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    call.recording_data = body
    call.recording_content_type = request.headers.get("content-type") or "audio/ogg"
    await db.commit()


@router.post("/calls/{call_id}/complete", status_code=status.HTTP_204_NO_CONTENT)
async def complete_call(
    call_id: uuid.UUID,
    payload: CallCompleteIn,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> None:
    result = await db.execute(select(Call).where(Call.id == call_id))
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    if call.status in _TERMINAL_STATUSES:
        # Not an error — a retried /complete (worker retries on network
        # failure) or a late report racing the API's own dispatch-failure
        # write (see create_outbound_call) would otherwise clobber whichever
        # terminal state got there first. First write wins; treat this as a
        # no-op success rather than 409, since the worker doesn't act on the
        # response either way.
        return

    call.status = _END_REASON_TO_STATUS.get(payload.end_reason, CallStatus.completed)
    call.duration_sec = payload.duration_sec
    call.end_reason = payload.end_reason
    call.ended_at = payload.ended_at
    if payload.transport is not None:
        call.transport = payload.transport
    if payload.tts_provider is not None:
        call.tts_provider = payload.tts_provider
    if payload.llm_model is not None:
        call.llm_model = payload.llm_model
    if payload.recording_key is not None:
        call.recording_key = payload.recording_key
    if payload.latency is not None:
        call.latency_stats = payload.latency.stats
        call.avg_latency_ms = payload.latency.avg_latency_ms
        call.p95_latency_ms = payload.latency.p95_latency_ms
    call.cost_estimate = estimate_cost(payload.duration_sec, call.transport, call.tts_provider)
    await db.commit()

    background_tasks.add_task(_finalize_call_side_effects, call_id, session_factory)
