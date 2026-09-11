import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.agent import Agent
from app.models.call import Call
from app.models.user import User
from app.schemas.agent import AgentCreate, AgentResponse, AgentUpdate, TestSessionResponse, Voice
from app.security import get_current_user
from app.services.livekit_service import (
    create_agent_dispatch_token,
    room_name_for_call,
)

router = APIRouter(tags=["agents"])

VOICE_CATALOG: list[Voice] = [
    Voice(id="arista", label="Arista (English, Female)", language="en"),
    Voice(id="atlas", label="Atlas (English, Male)", language="en"),
    Voice(id="celeste", label="Celeste (Urdu, Female)", language="ur"),
    Voice(id="orion", label="Orion (Urdu, Male)", language="ur"),
]


async def _get_org_agent(agent_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


@router.get("/voices", response_model=list[Voice])
async def list_voices() -> list[Voice]:
    return VOICE_CATALOG


@router.get("/agents", response_model=list[AgentResponse])
async def list_agents(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[Agent]:
    result = await db.execute(select(Agent).where(Agent.org_id == user.org_id))
    return list(result.scalars().all())


@router.post("/agents", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Agent:
    agent = Agent(org_id=user.org_id, name=payload.name, config=payload.config.model_dump())
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Agent:
    return await _get_org_agent(agent_id, user.org_id, db)


@router.patch("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    agent = await _get_org_agent(agent_id, user.org_id, db)
    if payload.name is not None:
        agent.name = payload.name
    if payload.config is not None:
        agent.config = payload.config.model_dump()
    await db.commit()
    await db.refresh(agent)
    return agent


@router.post("/agents/{agent_id}/test-session", response_model=TestSessionResponse)
async def create_test_session(
    agent_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> TestSessionResponse:
    agent = await _get_org_agent(agent_id, user.org_id, db)

    call = Call(
        org_id=agent.org_id,
        agent_id=agent.id,
        direction="test",
        status="in_progress",
        livekit_room_name="",
    )
    db.add(call)
    await db.flush()
    call.livekit_room_name = room_name_for_call(call.id)
    await db.commit()
    await db.refresh(call)

    token = create_agent_dispatch_token(call.livekit_room_name, agent.id, call.id)

    return TestSessionResponse(
        call_id=call.id,
        room_name=call.livekit_room_name,
        livekit_url=settings.livekit_url,
        token=token,
    )


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    agent = await _get_org_agent(agent_id, user.org_id, db)
    await db.delete(agent)
    await db.commit()
