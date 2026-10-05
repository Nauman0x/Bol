import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.agent import Agent
from app.models.phone_number import PhoneNumber
from app.schemas.phone_number import PhoneNumberCreate, PhoneNumberResponse, PhoneNumberUpdate
from app.security import CurrentUser

router = APIRouter(prefix="/phone_numbers", tags=["phone_numbers"])


async def _get_org_number(
    db: AsyncSession, org_id: uuid.UUID, number_id: uuid.UUID
) -> PhoneNumber:
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == number_id, PhoneNumber.org_id == org_id)
    )
    number = result.scalar_one_or_none()
    if number is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phone number not found")
    return number


async def _validate_inbound_agent(
    db: AsyncSession, org_id: uuid.UUID, agent_id: uuid.UUID | None
) -> None:
    if agent_id is None:
        return
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown agent_id")


@router.get("", response_model=list[PhoneNumberResponse])
async def list_numbers(
    current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[PhoneNumber]:
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.org_id == current_user.org_id)
    )
    return list(result.scalars().all())


@router.post("", response_model=PhoneNumberResponse, status_code=status.HTTP_201_CREATED)
async def create_number(
    payload: PhoneNumberCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PhoneNumber:
    existing = await db.execute(
        select(PhoneNumber).where(
            PhoneNumber.e164 == payload.e164, PhoneNumber.org_id == current_user.org_id
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Number already exists")
    await _validate_inbound_agent(db, current_user.org_id, payload.inbound_agent_id)

    number = PhoneNumber(
        org_id=current_user.org_id,
        e164=payload.e164,
        provider=payload.provider,
        livekit_trunk_id=payload.livekit_trunk_id,
        inbound_agent_id=payload.inbound_agent_id,
    )
    db.add(number)
    await db.commit()
    await db.refresh(number)
    return number


@router.patch("/{number_id}", response_model=PhoneNumberResponse)
async def update_number(
    number_id: uuid.UUID,
    payload: PhoneNumberUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PhoneNumber:
    number = await _get_org_number(db, current_user.org_id, number_id)
    fields_set = payload.model_fields_set
    if "inbound_agent_id" in fields_set:
        await _validate_inbound_agent(db, current_user.org_id, payload.inbound_agent_id)
        number.inbound_agent_id = payload.inbound_agent_id
    if "livekit_trunk_id" in fields_set:
        number.livekit_trunk_id = payload.livekit_trunk_id
    await db.commit()
    await db.refresh(number)
    return number


@router.delete("/{number_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_number(
    number_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    number = await _get_org_number(db, current_user.org_id, number_id)
    await db.delete(number)
    await db.commit()
