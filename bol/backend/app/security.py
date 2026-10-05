import asyncio
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.api_key import ApiKey
from app.models.user import User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)

# Shared with app/routers/api_keys.py, which mints keys in this shape.
API_KEY_PREFIX = "BOL_sk_"


async def hash_password(password: str) -> str:
    # bcrypt is deliberately slow (~50-100ms at the default cost factor) —
    # exactly what makes it a sound password hash also makes it block the
    # event loop for that long if called directly from an async route,
    # stalling every other in-flight request. Offloaded to a thread.
    return await asyncio.to_thread(pwd_context.hash, password)


async def verify_password(password: str, password_hash: str) -> bool:
    return await asyncio.to_thread(pwd_context.verify, password, password_hash)


def _create_token(subject: str, org_id: str, token_type: Literal["access", "refresh"]) -> str:
    if token_type == "access":
        expire_delta = timedelta(minutes=settings.access_token_expire_minutes)
    else:
        expire_delta = timedelta(days=settings.refresh_token_expire_days)
    expire = datetime.now(UTC) + expire_delta
    payload = {"sub": subject, "org_id": org_id, "type": token_type, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    return _create_token(str(user_id), str(org_id), "access")


def create_refresh_token(user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    return _create_token(str(user_id), str(org_id), "refresh")


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from exc


# Short-lived, call-scoped — the equivalent of an S3 presigned URL
# (app/services/recordings.py) but for a recording stored locally in the
# `calls` row instead of a bucket. An <audio> tag can't send an
# Authorization header, so the token travels in the query string and is
# checked against the specific call_id it was minted for.
_RECORDING_TOKEN_EXPIRES_MIN = 5


def create_recording_token(call_id: uuid.UUID) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=_RECORDING_TOKEN_EXPIRES_MIN)
    payload = {"call_id": str(call_id), "type": "recording", "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_recording_token(token: str, call_id: uuid.UUID) -> None:
    payload = decode_token(token)
    if payload.get("type") != "recording" or payload.get("call_id") != str(call_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )


# Only bump last_used_at if it's been at least this long since the last
# write — every authenticated request would otherwise be a DB write on top
# of the SELECT, purely to update a timestamp nobody needs to the second.
_LAST_USED_AT_THROTTLE = timedelta(seconds=60)


async def _authenticate_api_key(raw_key: str, db: AsyncSession) -> User | None:
    """API keys are org-scoped, not tied to a specific user (see ApiKey
    model) — a programmatic caller authenticates as the org's owner, the
    same identity that would have created the key. Candidates are narrowed
    by prefix (indexed) before the bcrypt verify, since key_hash can't be
    looked up directly."""
    prefix = raw_key[: len(API_KEY_PREFIX) + 6]
    result = await db.execute(select(ApiKey).where(ApiKey.prefix == prefix))
    for candidate in result.scalars().all():
        if await verify_password(raw_key, candidate.key_hash):
            now = datetime.now(UTC)
            last_used_at = candidate.last_used_at
            # SQLite (tests) doesn't preserve tzinfo on DateTime(timezone=True)
            # columns — see the same normalization in routers/calls.py.
            if last_used_at is not None and last_used_at.tzinfo is None:
                last_used_at = last_used_at.replace(tzinfo=UTC)
            if last_used_at is None or now - last_used_at > _LAST_USED_AT_THROTTLE:
                candidate.last_used_at = now
            owner_result = await db.execute(
                select(User)
                .where(User.org_id == candidate.org_id, User.role == UserRole.owner)
                .order_by(User.created_at)
                .limit(1)
            )
            owner = owner_result.scalar_one_or_none()
            if owner is None:
                await db.commit()
                return None
            await db.commit()
            return owner
    return None


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if credentials.credentials.startswith(API_KEY_PREFIX):
        user = await _authenticate_api_key(credentials.credentials, db)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        return user
    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong token type")
    user_id = payload.get("sub")
    try:
        user_uuid = uuid.UUID(user_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from exc
    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_internal_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    """Auth for worker → API calls (no user session; a shared service token)."""
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, settings.internal_service_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token"
        )


InternalAuth = Depends(require_internal_token)
