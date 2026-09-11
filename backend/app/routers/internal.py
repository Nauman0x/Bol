import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.agent import Agent
from app.models.call import Call, CallEvent
from app.schemas.agent import AgentResponse
from app.schemas.call import CallCompleteRequest, CallEventCreate, CallEventResponse
from app.security import verify_internal_token

router = APIRouter(prefix="/internal", tags=["internal"])


def _check_service_token(x_service_token: str = Header(default="")) -> None:
    verify_internal_token(x_service_token)


@router.get("/agents/{agent_id}", response_model=AgentResponse, dependencies=[Depends(_check_service_token)])
async def get_agent_internal(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


@router.post(
    "/calls/{call_id}/events",
    response_model=CallEventResponse,
    dependencies=[Depends(_check_service_token)],
)
async def create_call_event(
    call_id: uuid.UUID, payload: CallEventCreate, db: AsyncSession = Depends(get_db)
) -> CallEvent:
    event = CallEvent(call_id=call_id, type=payload.type, payload=payload.payload)
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


@router.post("/calls/{call_id}/complete", dependencies=[Depends(_check_service_token)])
async def complete_call(
    call_id: uuid.UUID, payload: CallCompleteRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    from datetime import datetime, timezone

    result = await db.execute(select(Call).where(Call.id == call_id))
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    call.status = "completed"
    call.ended_at = datetime.now(timezone.utc)
    call.duration_sec = payload.duration_sec
    call.end_reason = payload.end_reason
    await db.commit()
    return {"status": "ok"}
