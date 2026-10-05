"""Downloads and caches custom (user-uploaded) ambience clips for
BackgroundAudioPlayer.

Fetching is kicked off as soon as an agent's config is known (right in
worker/agent.py, before session setup) and only awaited later, after the
greeting has already been spoken — so a slow or unreachable clip can never
delay the call. Downloaded clips are cached to a per-process temp file keyed
by clip id; clips are immutable once uploaded (see app/routers/ambience.py),
so the cache never goes stale and warm workers skip the download entirely.
"""

import asyncio
import logging
import os
import tempfile
import uuid
from pathlib import Path

from worker.api_client import BOLApiClient

logger = logging.getLogger("BOL.worker")

_FETCH_TIMEOUT_SEC = 2.0
_CACHE_DIR = Path(tempfile.gettempdir()) / "BOL-ambience-cache"


def _clip_id_from_ambience(ambience: str | None) -> str | None:
    if not ambience or not ambience.startswith("custom:"):
        return None
    return ambience.removeprefix("custom:")


def start_prefetch(api: BOLApiClient, config: dict) -> "asyncio.Task[str | None] | None":
    """Call right after the agent config is fetched. Returns None (nothing
    to await later) when this agent has no custom ambience clip configured."""
    clip_id = _clip_id_from_ambience(config.get("ambience"))
    if clip_id is None:
        return None
    return asyncio.create_task(_fetch(api, clip_id))


async def _fetch(api: BOLApiClient, clip_id: str) -> str | None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached_path = _CACHE_DIR / clip_id
    if cached_path.exists():
        return str(cached_path)
    try:
        data = await api.get_ambience_clip(clip_id)
    except Exception:
        logger.exception("Failed to download ambience clip %s", clip_id)
        return None
    # Write to a per-download temp file and rename into place: a plain
    # write_bytes to cached_path would let a concurrent call on this same
    # worker process see .exists() == True (the check above) while the file
    # is still partially written, handing BackgroundAudioPlayer truncated
    # audio. os.replace is atomic on the same filesystem, so readers only
    # ever see either "not there yet" or "fully written". Also moved off the
    # event loop — these clips can be a few MB.
    tmp_path = _CACHE_DIR / f".{clip_id}.{uuid.uuid4().hex}.tmp"

    def _write_and_replace() -> None:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, cached_path)

    await asyncio.to_thread(_write_and_replace)
    return str(cached_path)


async def await_prefetch(task: "asyncio.Task[str | None] | None") -> str | None:
    """Await with a hard timeout so a slow/unreachable clip never delays the
    call — falls back to no ambience (returns None) instead. The download
    itself is shielded from the timeout, so if it finishes late it still
    populates the cache for the next call on this worker process.
    """
    if task is None:
        return None
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=_FETCH_TIMEOUT_SEC)
    except TimeoutError:
        logger.warning("Ambience clip fetch timed out after %ss, skipping", _FETCH_TIMEOUT_SEC)
        return None
    except Exception:
        logger.exception("Ambience clip fetch failed")
        return None
