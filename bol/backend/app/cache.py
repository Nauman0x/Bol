"""Thin async Redis cache helper. Used to avoid hitting the Fish Audio /
Chatterbox voice-list APIs on every /voices request. Redis is already part
of the stack (docker-compose.yml) but was previously unused by app code.

All failures (Redis down, bad JSON) are swallowed and treated as a cache
miss — a voice list must never fail to render just because the cache is
unavailable.
"""

import json
import logging
from typing import Any

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger("BOL.cache")

_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def cache_get_json(key: str) -> Any | None:
    try:
        raw = await _get_client().get(key)
        return json.loads(raw) if raw is not None else None
    except Exception:
        logger.warning("Redis GET failed for key=%s, treating as cache miss", key)
        return None


async def cache_set_json(key: str, value: Any, ttl_sec: int) -> None:
    try:
        await _get_client().set(key, json.dumps(value), ex=ttl_sec)
    except Exception:
        logger.warning("Redis SET failed for key=%s", key)


async def check_rate_limit(key: str, limit: int, window_sec: int) -> bool:
    """Sliding-window-ish counter (fixed window via INCR+EXPIRE — good enough
    for a login-guessing deterrent, not a precision limiter). Returns True if
    the action is allowed. Fails open on Redis errors: availability of login
    matters more than strict enforcement of the limit."""
    try:
        client = _get_client()
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_sec)
        return count <= limit
    except Exception:
        logger.warning("Redis rate-limit check failed for key=%s, failing open", key)
        return True
