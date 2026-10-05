"""User-uploaded background-ambience clips (org-scoped). See AgentConfig.ambience
in app/schemas/agent.py — a value of "custom:<clip id>" selects one of these.

Clips are immutable once uploaded (no update endpoint) — to change a clip,
delete it and upload a new one. That keeps the worker's cache key (the clip
id alone) valid for the clip's whole lifetime, no extra versioning needed.
"""

import logging
import uuid
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from mutagen import File as MutagenFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.ambience_clip import AmbienceClip
from app.schemas.ambience import AmbienceClipResponse
from app.security import CurrentUser

logger = logging.getLogger("BOL.api")

router = APIRouter(prefix="/ambience", tags=["ambience"])

_MAX_BYTES = 5 * 1024 * 1024
_MAX_DURATION_SEC = 120
_ALLOWED_CONTENT_TYPES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/ogg"}


async def _get_org_clip(db: AsyncSession, org_id: uuid.UUID, clip_id: uuid.UUID) -> AmbienceClip:
    result = await db.execute(
        select(AmbienceClip).where(AmbienceClip.id == clip_id, AmbienceClip.org_id == org_id)
    )
    clip = result.scalar_one_or_none()
    if clip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ambience clip not found"
        )
    return clip


@router.get("", response_model=list[AmbienceClipResponse])
async def list_ambience_clips(
    current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[AmbienceClip]:
    result = await db.execute(
        select(AmbienceClip).where(AmbienceClip.org_id == current_user.org_id)
    )
    return list(result.scalars().all())


@router.post("", response_model=AmbienceClipResponse, status_code=status.HTTP_201_CREATED)
async def upload_ambience_clip(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File()],
) -> AmbienceClip:
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported content type: {file.content_type}",
        )
    # Read one byte past the limit so an oversized file is caught by length,
    # not by silently truncating audio that then fails to decode later.
    data = await file.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="File exceeds 5MB limit"
        )

    try:
        audio = MutagenFile(BytesIO(data))
        duration_sec = audio.info.length if audio is not None and audio.info else None
        # mutagen's own sniff of the parsed bytes, not the client-declared
        # Content-Type header — this is what gets stored and later replayed
        # as the Content-Type for GET /internal/ambience/{clip_id} (see
        # app/routers/internal.py), so it shouldn't be client-controlled.
        detected_content_type = audio.mime[0] if audio is not None and audio.mime else None
    except Exception:
        duration_sec = None
        detected_content_type = None
    if duration_sec is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Could not read audio file"
        )
    if duration_sec > _MAX_DURATION_SEC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Clip exceeds {_MAX_DURATION_SEC}s limit",
        )

    clip = AmbienceClip(
        org_id=current_user.org_id,
        name=file.filename or "ambience",
        content_type=detected_content_type or file.content_type,
        duration_sec=int(duration_sec),
        data=data,
    )
    db.add(clip)
    await db.commit()
    await db.refresh(clip)
    return clip


@router.delete("/{clip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ambience_clip(
    clip_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    clip = await _get_org_clip(db, current_user.org_id, clip_id)
    await db.delete(clip)
    await db.commit()
