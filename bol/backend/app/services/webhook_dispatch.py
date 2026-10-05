"""Outbound event webhooks — org-configured HTTP callbacks fired on call
lifecycle events, HMAC-signed so receivers can verify authenticity.
"""

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from app.services.ssrf_guard import check_webhook_url

logger = logging.getLogger("BOL.webhooks")

_TIMEOUT_SEC = 10.0
SIGNATURE_HEADER = "X-BOL-Signature"
EVENT_HEADER = "X-BOL-Event"


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def dispatch(webhooks: list[tuple[str, str]], event: str, payload: dict[str, Any]) -> None:
    """webhooks: (url, secret) pairs already filtered to active subscribers
    of `event`. Best-effort and one attempt each — a failing webhook must
    never affect another, or whatever triggered the dispatch."""
    if not webhooks:
        return
    body = json.dumps({"event": event, "data": payload}, default=str).encode()
    async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
        for url, secret in webhooks:
            try:
                # check_webhook_url also runs at subscription time
                # (routers/webhooks.py), but re-resolving here closes a
                # DNS-rebind window: a URL that resolved to a public IP when
                # it was saved could point at an internal address by the
                # time delivery actually happens. The in-call webhook tool
                # (worker/tools.py) already re-checks per call for the same
                # reason — this brings org-level subscriptions in line.
                await check_webhook_url(url)
                resp = await client.post(
                    url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        SIGNATURE_HEADER: sign(secret, body),
                        EVENT_HEADER: event,
                    },
                )
                resp.raise_for_status()
            except ValueError:
                logger.warning("Webhook delivery to %s blocked", url, exc_info=True)
            except httpx.HTTPError:
                logger.warning("Webhook delivery to %s failed", url, exc_info=True)
