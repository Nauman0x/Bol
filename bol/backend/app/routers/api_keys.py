import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.api_key import ApiKey
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyResponse
from app.security import API_KEY_PREFIX, CurrentUser, hash_password

router = APIRouter(prefix="/api_keys", tags=["api_keys"])

_KEY_PREFIX = API_KEY_PREFIX


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[ApiKey]:
    result = await db.execute(select(ApiKey).where(ApiKey.org_id == current_user.org_id))
    return list(result.scalars().all())


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiKeyCreated:
    raw_key = f"{_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    api_key = ApiKey(
        org_id=current_user.org_id,
        name=payload.name,
        key_hash=await hash_password(raw_key),
        prefix=raw_key[: len(_KEY_PREFIX) + 6],
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    # raw_key is returned here and never again — only key_hash is persisted.
    return ApiKeyCreated(
        id=api_key.id,
        name=api_key.name,
        prefix=api_key.prefix,
        created_at=api_key.created_at,
        key=raw_key,
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.org_id == current_user.org_id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    await db.delete(api_key)
    await db.commit()
