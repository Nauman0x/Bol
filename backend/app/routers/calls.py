import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.call import Call, CallEvent
from app.models.user import User
from app.schemas.call import CallEventResponse, CallResponse
from app.security import get_current_user

router = APIRouter(prefix="/calls", tags=["calls"])


@router.get("", response_model=list[CallResponse])
async def list_calls(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[Call]:
    result = await db.execute(
        select(Call).where(Call.org_id == user.org_id).order_by(Call.started_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{call_id}", response_model=CallResponse)
async def get_call(
    call_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Call:
    result = await db.execute(select(Call).where(Call.id == call_id, Call.org_id == user.org_id))
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    return call


@router.get("/{call_id}/events", response_model=list[CallEventResponse])
async def list_call_events(
    call_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[CallEvent]:
    call_result = await db.execute(select(Call).where(Call.id == call_id, Call.org_id == user.org_id))
    if call_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    events_result = await db.execute(
        select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.ts.asc())
    )
    return list(events_result.scalars().all())
