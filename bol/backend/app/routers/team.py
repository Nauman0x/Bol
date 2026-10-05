import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.schemas.organization import OrganizationResponse, OrganizationUpdate
from app.schemas.team import TeamMemberInvite, TeamMemberInvited, TeamMemberResponse
from app.security import CurrentUser, hash_password

router = APIRouter(tags=["team"])


@router.get("/team", response_model=list[TeamMemberResponse])
async def list_team(
    current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[User]:
    result = await db.execute(select(User).where(User.org_id == current_user.org_id))
    return list(result.scalars().all())


@router.post("/team/invite", response_model=TeamMemberInvited, status_code=status.HTTP_201_CREATED)
async def invite_team_member(
    payload: TeamMemberInvite,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TeamMemberInvited:
    if current_user.role not in (UserRole.owner, UserRole.admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only owners and admins can invite"
        )
    if payload.role == UserRole.owner and current_user.role != UserRole.owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only owners can invite another owner"
        )

    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    # MVP invite flow: generate a temp password shown once to the inviter, who
    # passes it along out-of-band. No email delivery — that's a later concern.
    temp_password = secrets.token_urlsafe(12)
    user = User(
        org_id=current_user.org_id,
        email=payload.email,
        password_hash=await hash_password(temp_password),
        name=payload.name,
        role=payload.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return TeamMemberInvited(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        temp_password=temp_password,
    )


@router.get("/organization", response_model=OrganizationResponse)
async def get_organization(
    current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> Organization:
    result = await db.execute(
        select(Organization).where(Organization.id == current_user.org_id)
    )
    return result.scalar_one()


@router.patch("/organization", response_model=OrganizationResponse)
async def update_organization(
    payload: OrganizationUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Organization:
    if current_user.role not in (UserRole.owner, UserRole.admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners and admins can rename the org",
        )
    result = await db.execute(
        select(Organization).where(Organization.id == current_user.org_id)
    )
    org = result.scalar_one()
    org.name = payload.name
    await db.commit()
    await db.refresh(org)
    return org
