import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.webhook import Webhook
from app.schemas.webhook import WebhookCreate, WebhookCreated, WebhookResponse
from app.security import CurrentUser
from app.services.ssrf_guard import check_webhook_url

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[Webhook]:
    result = await db.execute(select(Webhook).where(Webhook.org_id == current_user.org_id))
    return list(result.scalars().all())


@router.post("", response_model=WebhookCreated, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WebhookCreated:
    try:
        await check_webhook_url(payload.url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    webhook = Webhook(
        org_id=current_user.org_id,
        url=payload.url,
        secret=secrets.token_urlsafe(32),
        events=payload.events,
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)

    # secret is returned here and never again — only it is persisted.
    return WebhookCreated(
        id=webhook.id,
        url=webhook.url,
        events=webhook.events,
        is_active=webhook.is_active,
        created_at=webhook.created_at,
        secret=webhook.secret,
    )


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == current_user.org_id)
    )
    webhook = result.scalar_one_or_none()
    if webhook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    await db.delete(webhook)
    await db.commit()
