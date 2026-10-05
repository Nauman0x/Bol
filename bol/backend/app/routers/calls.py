import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db
from app.models.agent import Agent
from app.models.call import Call, CallDirection, CallStatus
from app.models.phone_number import PhoneNumber
from app.schemas.call import (
    CallDetailResponse,
    CallResponse,
    ListenSessionResponse,
    OutboundCallCreate,
    RecordingUrlResponse,
)
from app.security import CurrentUser, create_recording_token, verify_recording_token
from app.services import recordings
from app.services.livekit_service import (
    LiveKitNotConfiguredError,
    LiveKitService,
    get_livekit_service,
)
from app.tts_providers import resolve_llm_model, resolve_tts_provider

logger = logging.getLogger("BOL.api")

router = APIRouter(prefix="/calls", tags=["calls"])

_ACTIVE_STATUSES = (CallStatus.queued, CallStatus.ringing, CallStatus.in_progress)
_STATUS_QUERY = Query(default=None, alias="status")

# A non-terminal call still running well past its own agent's
# max_call_duration_sec almost certainly means the worker died before ever
# calling /complete (crash, OOM, SIGKILL) — that's the only thing that
# normally clears a call (see worker/agent.py's shutdown callback). Without
# this, a stuck row occupies an org's concurrency slot forever. Grace period
# is on top of the agent's own limit, which the worker itself enforces
# (_enforce_max_duration) — so a healthy worker always finishes well inside
# it; this is purely a dead-worker detector. Checked lazily, right here,
# rather than via a background scheduler — this is the one place that
# actually needs the concurrency count to be accurate.
_REAP_GRACE_SEC = 120

_PROVIDER_CONCURRENCY_LIMITS = {
    "fish": lambda: settings.fish_max_concurrent_calls,
    "chatterbox": lambda: settings.chatterbox_max_concurrent_calls,
}


async def _check_provider_concurrency(db: AsyncSession, tts_provider: str) -> None:
    limit_fn = _PROVIDER_CONCURRENCY_LIMITS.get(tts_provider)
    if limit_fn is None:
        return
    limit = limit_fn()
    # This check is platform-wide (see below), so unlike the org-scoped
    # concurrency check, a stale/stuck call from *any* org sits here until
    # someone in that specific org happens to make another call and
    # triggers the org-scoped reap — which could be a long time, and
    # meanwhile it wrongly counts against every other org's shared Fish/
    # Chatterbox capacity. Reap platform-wide first so a dead worker's
    # leftover row can't do that.
    await _reap_stale_calls(db, org_id=None)

    # Platform-wide, not org-scoped — unlike max_concurrent_calls, this cap
    # comes from a single shared Fish API key / Chatterbox GPU pool that
    # every org's calls draw from together.
    active_count_result = await db.execute(
        select(func.count())
        .select_from(Call)
        .where(Call.status.in_(_ACTIVE_STATUSES), Call.tts_provider == tts_provider)
    )
    if active_count_result.scalar_one() >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Concurrent call limit for TTS provider '{tts_provider}' ({limit}) reached",
        )


async def _reap_stale_calls(db: AsyncSession, org_id: uuid.UUID | None) -> None:
    """org_id=None reaps across every org — used by the platform-wide
    provider-concurrency check above, which has no single org to scope to."""
    query = (
        select(Call, Agent.config)
        .join(Agent, Agent.id == Call.agent_id)
        .where(Call.status.in_(_ACTIVE_STATUSES))
    )
    if org_id is not None:
        query = query.where(Call.org_id == org_id)
    result = await db.execute(query)
    now = datetime.now(UTC)
    reaped = False
    for call, agent_config in result.all():
        max_duration = agent_config.get("max_call_duration_sec", 600)
        created_at = call.created_at
        if created_at.tzinfo is None:
            # SQLite (tests) doesn't preserve tzinfo on DateTime(timezone=True)
            # columns — see the same normalization in hangup_call below.
            created_at = created_at.replace(tzinfo=UTC)
        if now < created_at + timedelta(seconds=max_duration + _REAP_GRACE_SEC):
            continue
        logger.warning("Reaping stale call %s (stuck at %s)", call.id, call.status)
        call.status = CallStatus.failed
        call.end_reason = "worker_lost"
        call.ended_at = now
        reaped = True
    if reaped:
        await db.commit()


async def _lock_org_for_call_creation(db: AsyncSession, org_id: uuid.UUID) -> None:
    """Serializes concurrent outbound-call creation per org so the active-call
    COUNT the concurrency check reads below can't go stale before the new
    call's INSERT commits — without this, two requests can both pass the
    check and jointly exceed max_concurrent_calls. Transaction-scoped, so it
    releases automatically at the commit that follows the INSERT. No-op
    outside Postgres — tests run SQLite and aren't exercised concurrently."""
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": str(org_id)})


async def _get_org_call(db: AsyncSession, org_id: uuid.UUID, call_id: uuid.UUID) -> Call:
    result = await db.execute(select(Call).where(Call.id == call_id, Call.org_id == org_id))
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    return call


@router.get("", response_model=list[CallResponse])
async def list_calls(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    agent_id: uuid.UUID | None = None,
    direction: CallDirection | None = None,
    call_status: CallStatus | None = _STATUS_QUERY,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Call]:
    query = select(Call).where(Call.org_id == current_user.org_id)
    if agent_id is not None:
        query = query.where(Call.agent_id == agent_id)
    if direction is not None:
        query = query.where(Call.direction == direction)
    if call_status is not None:
        query = query.where(Call.status == call_status)
    if since is not None:
        query = query.where(Call.created_at >= since)
    if until is not None:
        query = query.where(Call.created_at <= until)
    query = query.order_by(Call.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{call_id}", response_model=CallDetailResponse)
async def get_call(
    call_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Call:
    result = await db.execute(
        select(Call)
        .where(Call.id == call_id, Call.org_id == current_user.org_id)
        .options(selectinload(Call.events))
    )
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    return call


@router.get("/{call_id}/recording", response_model=RecordingUrlResponse)
async def get_call_recording(
    call_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RecordingUrlResponse:
    """A short-lived signed URL — generated fresh on every request, never
    stored. Either a presigned S3 URL (app/services/recordings.py) or, when
    no bucket is configured, a token-guarded URL back at our own
    /calls/{id}/recording/raw (app/security.py:create_recording_token)."""
    call = await _get_org_call(db, current_user.org_id, call_id)
    if call.recording_content_type is not None:
        token = create_recording_token(call.id)
        url = f"{settings.api_base_url}/calls/{call.id}/recording/raw?token={token}"
        return RecordingUrlResponse(url=url)
    if call.recording_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No recording for this call"
        )
    if not recordings.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recording storage is not configured",
        )
    return RecordingUrlResponse(url=recordings.presign_recording_url(call.recording_key))


@router.get("/{call_id}/recording/raw")
async def get_call_recording_raw(
    call_id: uuid.UUID,
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    download: bool = False,
) -> Response:
    """Token-guarded, not session-guarded — an <audio> tag can't send an
    Authorization header, so this checks the short-lived token from
    get_call_recording above instead of CurrentUser. Not org-scoped for the
    same reason app/routers/internal.py's ambience route isn't: the token
    itself, not org membership, is what authorizes this request.

    `download=true` sets Content-Disposition: attachment so the browser
    saves the file instead of trying to play it — the default (inline) is
    what the <audio> player itself uses, and cross-origin `<a download>`
    can't be relied on to force it (the frontend runs on a different origin
    than this API in local dev)."""
    verify_recording_token(token, call_id)
    result = await db.execute(select(Call).where(Call.id == call_id))
    call = result.scalar_one_or_none()
    if call is None or call.recording_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No recording for this call"
        )
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="call-{call_id}.ogg"'
    return Response(
        content=call.recording_data, media_type=call.recording_content_type, headers=headers
    )


@router.post("/outbound", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
async def create_outbound_call(
    payload: OutboundCallCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    livekit: Annotated[LiveKitService, Depends(get_livekit_service)],
) -> Call:
    agent_result = await db.execute(
        select(Agent).where(Agent.id == payload.agent_id, Agent.org_id == current_user.org_id)
    )
    agent = agent_result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown agent_id")
    if not agent.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent is not active")

    await _reap_stale_calls(db, current_user.org_id)
    await _lock_org_for_call_creation(db, current_user.org_id)

    active_count_result = await db.execute(
        select(func.count())
        .select_from(Call)
        .where(Call.org_id == current_user.org_id, Call.status.in_(_ACTIVE_STATUSES))
    )
    if active_count_result.scalar_one() >= settings.max_concurrent_calls:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Concurrent call limit ({settings.max_concurrent_calls}) reached",
        )
    resolved_tts_provider = resolve_tts_provider(agent.config)
    await _check_provider_concurrency(db, resolved_tts_provider)

    phone_number: PhoneNumber | None = None
    if payload.phone_number_id is not None:
        number_result = await db.execute(
            select(PhoneNumber).where(
                PhoneNumber.id == payload.phone_number_id, PhoneNumber.org_id == current_user.org_id
            )
        )
        phone_number = number_result.scalar_one_or_none()
        if phone_number is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown phone_number_id"
            )
    else:
        number_result = await db.execute(
            select(PhoneNumber)
            .where(PhoneNumber.org_id == current_user.org_id)
            .order_by(PhoneNumber.created_at)
            .limit(1)
        )
        phone_number = number_result.scalar_one_or_none()
        if phone_number is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No phone number configured for this organization",
            )

    call = Call(
        org_id=current_user.org_id,
        agent_id=agent.id,
        phone_number_id=phone_number.id,
        direction=CallDirection.outbound,
        to_number=payload.to_number,
        from_number=phone_number.e164,
        status=CallStatus.queued,
        transport="telephony",
        tts_provider=resolved_tts_provider,
        llm_model=resolve_llm_model(agent.config),
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)

    room_name = f"BOL-call-{call.id}"
    room_created = False
    try:
        await livekit.create_call_room(room_name, call.id, agent.id, transport="telephony")
        room_created = True
        await livekit.dial_outbound(
            room_name,
            payload.to_number,
            from_trunk_id=phone_number.livekit_trunk_id,
            from_number=phone_number.e164,
        )
    except Exception:
        logger.exception("Failed to dispatch outbound call %s", call.id)
        if room_created:
            # The room has an agent dispatch attached — if we leave it, a
            # worker picks up the job, finds no SIP participant, waits out
            # the full answer timeout, then reports no_answer and overwrites
            # the dispatch_failed status we're about to set below.
            try:
                await livekit.delete_room(room_name)
            except Exception:
                logger.exception("Failed to clean up orphaned room for call %s", call.id)
        call.status = CallStatus.failed
        call.end_reason = "dispatch_failed"
        call.ended_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(call)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to dispatch call via LiveKit"
        ) from None
    finally:
        await livekit.aclose()

    call.status = CallStatus.ringing
    call.livekit_room_name = room_name
    call.started_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(call)
    return call


@router.get("/{call_id}/listen", response_model=ListenSessionResponse)
async def listen_to_call(
    call_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    livekit: Annotated[LiveKitService, Depends(get_livekit_service)],
) -> ListenSessionResponse:
    """A subscribe-only LiveKit token so an operator can listen in on a call
    that's happening right now — see LiveKitService.generate_listen_token."""
    call = await _get_org_call(db, current_user.org_id, call_id)
    if call.status not in _ACTIVE_STATUSES or not call.livekit_room_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Call is not active")

    try:
        token = livekit.generate_listen_token(
            call.livekit_room_name,
            identity=f"listener-{current_user.id}",
            name=f"{current_user.name} (listening)",
        )
    except LiveKitNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from None

    return ListenSessionResponse(
        livekit_url=settings.livekit_url, room_name=call.livekit_room_name, token=token
    )


@router.post("/{call_id}/hangup", response_model=CallResponse)
async def hangup_call(
    call_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    livekit: Annotated[LiveKitService, Depends(get_livekit_service)],
) -> Call:
    call = await _get_org_call(db, current_user.org_id, call_id)
    if call.status not in _ACTIVE_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Call is not active")

    if call.livekit_room_name:
        try:
            await livekit.delete_room(call.livekit_room_name)
        except Exception:
            logger.exception("Failed to delete LiveKit room for call %s", call.id)
        finally:
            await livekit.aclose()

    now = datetime.now(UTC)
    call.status = CallStatus.completed
    call.end_reason = "operator_hangup"
    call.ended_at = now
    if call.started_at:
        # SQLite (used in tests) doesn't preserve tzinfo on DateTime(timezone=True)
        # columns, so a value read back from the DB can come back naive even though
        # it was written as UTC-aware. Postgres doesn't have this problem, but
        # normalize defensively so the arithmetic below never depends on the driver.
        started_at = call.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        call.duration_sec = int((now - started_at).total_seconds())
    await db.commit()
    await db.refresh(call)
    return call
