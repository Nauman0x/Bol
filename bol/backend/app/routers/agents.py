import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.agent import Agent
from app.models.call import Call, CallDirection, CallStatus
from app.routers.calls import (
    _ACTIVE_STATUSES,
    _check_provider_concurrency,
    _lock_org_for_call_creation,
    _reap_stale_calls,
)
from app.schemas.agent import AgentCreate, AgentResponse, AgentUpdate, TestSessionResponse
from app.security import CurrentUser
from app.services.livekit_service import (
    LiveKitNotConfiguredError,
    LiveKitService,
    get_livekit_service,
)
from app.tts_providers import resolve_llm_model, resolve_tts_provider

logger = logging.getLogger("BOL.api")

router = APIRouter(prefix="/agents", tags=["agents"])


async def _get_org_agent(db: AsyncSession, org_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[Agent]:
    result = await db.execute(select(Agent).where(Agent.org_id == current_user.org_id))
    return list(result.scalars().all())


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Agent:
    agent = Agent(
        org_id=current_user.org_id,
        name=payload.name,
        config=payload.config.model_dump(),
        # mode="json" so a ToolRef's UUID tool_id serializes to str —
        # the JSON column would otherwise reject a raw UUID at insert time.
        tools=[t.model_dump(mode="json") for t in payload.tools],
        is_active=payload.is_active,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Agent:
    return await _get_org_agent(db, current_user.org_id, agent_id)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Agent:
    agent = await _get_org_agent(db, current_user.org_id, agent_id)
    if payload.name is not None:
        agent.name = payload.name
    if payload.config is not None:
        agent.config = payload.config.model_dump()
    if payload.tools is not None:
        agent.tools = [t.model_dump(mode="json") for t in payload.tools]
    if payload.is_active is not None:
        agent.is_active = payload.is_active
    await db.commit()
    await db.refresh(agent)
    return agent


@router.post("/{agent_id}/test-session", response_model=TestSessionResponse)
async def create_test_session(
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    livekit: Annotated[LiveKitService, Depends(get_livekit_service)],
) -> TestSessionResponse:
    """Lets the agent-builder UI talk to the agent from the browser mic — no
    telephony cost, no phone number needed. Gets a real Call row (direction
    "test") like any other call, so its transcript and latency are tracked
    the same way — this used to pass call_id=None and silently discard both
    (EventReporter no-ops without a call_id)."""
    agent = await _get_org_agent(db, current_user.org_id, agent_id)
    if not agent.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent is not active")

    await _reap_stale_calls(db, current_user.org_id)
    # Without this, two concurrent test-session requests can both pass the
    # count check below and jointly exceed max_concurrent_calls — the
    # outbound-call path already guards against this same race (calls.py);
    # this endpoint just hadn't been given the same lock.
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

    call = Call(
        org_id=current_user.org_id,
        agent_id=agent.id,
        direction=CallDirection.test,
        to_number="(browser test)",
        from_number="(browser test)",
        status=CallStatus.queued,
        transport="webrtc",
        tts_provider=resolved_tts_provider,
        llm_model=resolve_llm_model(agent.config),
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)

    room_name = f"BOL-test-{agent.id}-{uuid.uuid4().hex[:8]}"
    room_created = False
    try:
        await livekit.create_call_room(room_name, call.id, agent.id, transport="webrtc")
        room_created = True
        token = livekit.generate_join_token(
            room_name, identity=f"user-{current_user.id}", name=current_user.name
        )
    except LiveKitNotConfiguredError as exc:
        # Operator-facing config state (missing env var), safe to surface
        # directly rather than a generic 502 — see app/services/livekit_service.py.
        logger.warning("Test session for agent %s blocked on config: %s", agent.id, exc)
        call.status = CallStatus.failed
        call.end_reason = "dispatch_failed"
        call.ended_at = datetime.now(UTC)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from None
    except Exception:
        logger.exception("Failed to create test session for agent %s", agent.id)
        if room_created:
            # The room has an agent dispatch attached — if we leave it, a
            # worker picks up the job with no way to greet anyone (this is
            # a browser test call, there's no caller to answer for), same
            # orphaned-room concern as the outbound-call path (calls.py).
            try:
                await livekit.delete_room(room_name)
            except Exception:
                logger.exception("Failed to clean up orphaned room for call %s", call.id)
        call.status = CallStatus.failed
        call.end_reason = "dispatch_failed"
        call.ended_at = datetime.now(UTC)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to start test session"
        ) from None
    finally:
        await livekit.aclose()

    call.livekit_room_name = room_name
    call.started_at = datetime.now(UTC)
    await db.commit()

    return TestSessionResponse(
        livekit_url=settings.livekit_url, room_name=room_name, token=token, call_id=call.id
    )


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    agent = await _get_org_agent(db, current_user.org_id, agent_id)
    await db.delete(agent)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent has call history and cannot be deleted",
        ) from exc
