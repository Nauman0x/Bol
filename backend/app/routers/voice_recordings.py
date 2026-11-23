import hashlib
import re
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.voice_recording import VoiceClip, VoiceSession
from app.schemas.voice_recording import (
    VoiceProgressResponse,
    VoiceSessionCreate,
    VoiceSessionCreateResponse,
)
from app.security import verify_internal_token

router = APIRouter(prefix="/api", tags=["voice-recordings"])

ALLOWED_GENDERS = {"Female", "Male", "Prefer not to say"}
ALLOWED_AGE_BANDS = {"Under 18", "18-24", "25-34", "35-49", "50+"}
ALLOWED_ENVIRONMENTS = {"Quiet room", "Some background noise", "Noisy place"}
EXTENSION_BY_MIME = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
}


def _ip_hash(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",", 1)[0].strip() if forwarded else (
        request.client.host if request.client else "unknown"
    )
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:64]


def _check_speaker_id(speaker: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{8}", speaker):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid speaker ID")


def _check_service_token(x_service_token: str = Header(default="")) -> None:
    verify_internal_token(x_service_token)


@router.post("/session", response_model=VoiceSessionCreateResponse)
async def create_voice_session(
    payload: VoiceSessionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> VoiceSessionCreateResponse:
    if not payload.consent:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Consent is required")
    if payload.gender not in ALLOWED_GENDERS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid gender")
    if payload.age_band not in ALLOWED_AGE_BANDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid age group")
    if payload.environment not in ALLOWED_ENVIRONMENTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid environment")

    while True:
        speaker_id = secrets.token_hex(4)
        existing = await db.execute(select(VoiceSession).where(VoiceSession.speaker_id == speaker_id))
        if existing.scalar_one_or_none() is None:
            break

    voice_session = VoiceSession(
        speaker_id=speaker_id,
        consent=payload.consent,
        gender=payload.gender,
        age_band=payload.age_band,
        region=payload.region.strip(),
        mother_tongue=payload.mother_tongue.strip() if payload.mother_tongue else None,
        device=payload.device,
        environment=payload.environment,
        script=payload.script,
        ip_hash=_ip_hash(request),
        user_agent=request.headers.get("user-agent", "")[:500],
    )
    db.add(voice_session)
    await db.commit()
    return VoiceSessionCreateResponse(speakerId=speaker_id)


@router.get("/progress", response_model=VoiceProgressResponse)
async def voice_progress(speaker: str, db: AsyncSession = Depends(get_db)) -> VoiceProgressResponse:
    _check_speaker_id(speaker)
    session = await db.execute(select(VoiceSession).where(VoiceSession.speaker_id == speaker))
    if session.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Speaker not found")

    result = await db.execute(
        select(VoiceClip.sentence_id)
        .where(VoiceClip.speaker_id == speaker)
        .order_by(VoiceClip.created_at.asc())
    )
    return VoiceProgressResponse(done=list(result.scalars().all()))


@router.post("/clip")
async def upload_voice_clip(
    request: Request,
    speaker: str,
    sentence: str,
    duration: int = 0,
    content_type: str | None = Header(default=None, alias="Content-Type"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    _check_speaker_id(speaker)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", sentence):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sentence ID")
    if duration < 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Recording is too short")
    if duration > 10 * 60 * 1000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Recording is too long")

    session = await db.execute(select(VoiceSession).where(VoiceSession.speaker_id == speaker))
    if session.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Speaker not found")

    mime = (content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    if mime not in EXTENSION_BY_MIME:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported audio format")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty recording")
    if len(body) > settings.max_voice_upload_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Recording exceeds upload limit")

    digest = hashlib.sha256(body).hexdigest()
    speaker_dir = Path(settings.voice_data_dir).resolve() / "speakers" / speaker
    speaker_dir.mkdir(parents=True, exist_ok=True)
    file_path = speaker_dir / f"{speaker}_{sentence}_{digest[:12]}{EXTENSION_BY_MIME[mime]}"

    temporary = file_path.with_suffix(file_path.suffix + ".tmp")
    temporary.write_bytes(body)
    temporary.replace(file_path)

    existing = await db.execute(
        select(VoiceClip).where(
            VoiceClip.speaker_id == speaker,
            VoiceClip.sentence_id == sentence,
        )
    )
    clip = existing.scalar_one_or_none()
    if clip is None:
        clip = VoiceClip(
            speaker_id=speaker,
            sentence_id=sentence,
            duration_ms=duration,
            mime_type=mime,
            sha256=digest,
            byte_size=len(body),
            file_path=str(file_path),
        )
        db.add(clip)
    else:
        clip.duration_ms = duration
        clip.mime_type = mime
        clip.sha256 = digest
        clip.byte_size = len(body)
        clip.file_path = str(file_path)

    await db.commit()
    return {"ok": True, "speakerId": speaker, "sentenceId": sentence}


@router.delete("/session/{speaker}", dependencies=[Depends(_check_service_token)])
async def delete_voice_session(speaker: str, db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    _check_speaker_id(speaker)
    result = await db.execute(select(VoiceSession).where(VoiceSession.speaker_id == speaker))
    voice_session = result.scalar_one_or_none()
    if voice_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Speaker not found")

    await db.delete(voice_session)
    await db.commit()

    speaker_dir = Path(settings.voice_data_dir).resolve() / "speakers" / speaker
    if speaker_dir.exists():
        for path in speaker_dir.iterdir():
            if path.is_file():
                path.unlink()
        speaker_dir.rmdir()

    return {"ok": True, "deletedSpeaker": speaker}


@router.get("/admin/export", dependencies=[Depends(_check_service_token)])
async def export_voice_recordings(
    target_speaker: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    export_dir = Path(settings.voice_data_dir).resolve() / "evaluation_export" / str(int(time.time()))
    references_dir = export_dir / "references"
    human_other_dir = export_dir / "human_other"
    references_dir.mkdir(parents=True, exist_ok=True)
    human_other_dir.mkdir(parents=True, exist_ok=True)

    if target_speaker:
        _check_speaker_id(target_speaker)
        result = await db.execute(select(VoiceSession).where(VoiceSession.speaker_id == target_speaker))
        sessions = [row for row in result.scalars().all()]
    else:
        result = await db.execute(select(VoiceSession))
        sessions = list(result.scalars().all())

    manifest: list[dict[str, object]] = []
    for voice_session in sessions:
        clips = await db.execute(select(VoiceClip).where(VoiceClip.speaker_id == voice_session.speaker_id))
        category = references_dir if target_speaker else human_other_dir
        speaker_dir = category / voice_session.speaker_id

        for clip in clips.scalars().all():
            source = Path(clip.file_path)
            if not source.exists():
                continue
            speaker_dir.mkdir(parents=True, exist_ok=True)
            destination = speaker_dir / f"{clip.sentence_id}{source.suffix}"
            destination.write_bytes(source.read_bytes())
            manifest.append({
                "speaker_id": voice_session.speaker_id,
                "sentence_id": clip.sentence_id,
                "exported_path": str(destination),
                "gender": voice_session.gender,
                "age_band": voice_session.age_band,
                "region": voice_session.region,
                "mother_tongue": voice_session.mother_tongue,
                "device": voice_session.device,
                "environment": voice_session.environment,
            })

    return {"exportDirectory": str(export_dir), "manifest": manifest}
