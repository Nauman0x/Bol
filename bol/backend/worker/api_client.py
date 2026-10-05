"""HTTP client the worker uses to talk to the BOL API. The worker never opens
its own DB connection — this is the only way it reads config or reports state,
which is what lets worker processes scale horizontally without DB coordination.
"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("BOL.worker")

_MAX_RETRIES = 3
_RETRY_BACKOFF_SEC = 1.5


class BOLApiClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url or settings.api_base_url).rstrip("/")
        self._token = token or settings.internal_service_token
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=10.0,
            transport=transport,
        )

    async def get_agent_config(self, agent_id: str) -> dict[str, Any]:
        resp = await self._client.get(f"/internal/agents/{agent_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_ambience_clip(self, clip_id: str) -> bytes:
        resp = await self._client.get(f"/internal/ambience/{clip_id}")
        resp.raise_for_status()
        return resp.content

    async def create_inbound_call(
        self, to_number: str, from_number: str, livekit_room_name: str
    ) -> dict[str, Any]:
        resp = await self._client.post(
            "/internal/calls/inbound",
            json={
                "to_number": to_number,
                "from_number": from_number,
                "livekit_room_name": livekit_room_name,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def get_agent_tools(self, agent_id: str) -> list[dict[str, Any]]:
        """Resolved Tool rows (secrets decrypted) for this agent's tool_ref
        entries — see app/routers/internal.py:get_agent_tools_for_worker and
        app/schemas/tool.py:ToolResolved."""
        resp = await self._client.get(f"/internal/agents/{agent_id}/tools")
        resp.raise_for_status()
        return resp.json()

    async def search_knowledge(self, org_id: str, query: str) -> list[str]:
        resp = await self._client.post(
            "/internal/knowledge/search", json={"org_id": org_id, "query": query}
        )
        resp.raise_for_status()
        return resp.json()["chunks"]

    async def report_answered(self, call_id: str) -> None:
        """Best-effort, not retried like complete_call — a missed answered
        flag just means the call briefly shows as queued/ringing a bit
        longer than it should; complete_call (which IS retried) is what
        actually finalizes the row, so losing this one call isn't fatal."""
        try:
            resp = await self._client.post(f"/internal/calls/{call_id}/answered")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to report call %s answered: %s", call_id, exc)

    async def upload_recording(self, call_id: str, data: bytes, content_type: str) -> None:
        """Best-effort, like report_answered above — a failed upload just
        means this one call has no recording, never worth failing the call
        itself over."""
        try:
            resp = await self._client.put(
                f"/internal/calls/{call_id}/recording",
                content=data,
                headers={"Content-Type": content_type},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to upload recording for call %s: %s", call_id, exc)

    async def _post_with_retry(self, path: str, json: dict[str, Any]) -> None:
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = await self._client.post(path, json=json)
                resp.raise_for_status()
                return
            except httpx.HTTPStatusError as exc:
                # A 4xx means the API rejected the request as-is (bad
                # payload, unknown call_id) — retrying it verbatim can only
                # produce the same 4xx. Worse, this runs from _cleanup on the
                # shutdown path, where each retry's sleep eats into the
                # job's shutdown grace period; only network/5xx failures are
                # worth that cost.
                if exc.response.status_code < 500:
                    logger.warning(
                        "POST %s rejected permanently (%s): %s",
                        path,
                        exc.response.status_code,
                        exc,
                    )
                    return
                last_exc = exc
                logger.warning(
                    "POST %s failed (attempt %d/%d): %s", path, attempt, _MAX_RETRIES, exc
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BACKOFF_SEC * attempt)
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "POST %s failed (attempt %d/%d): %s", path, attempt, _MAX_RETRIES, exc
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BACKOFF_SEC * attempt)
        logger.error(
            "POST %s permanently failed after %d attempts: %s", path, _MAX_RETRIES, last_exc
        )

    async def report_events(self, call_id: str, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        await self._post_with_retry(f"/internal/calls/{call_id}/events", {"events": events})

    async def complete_call(
        self,
        call_id: str,
        duration_sec: int,
        end_reason: str,
        *,
        transport: str | None = None,
        tts_provider: str | None = None,
        llm_model: str | None = None,
        latency_stats: dict[str, Any] | None = None,
        avg_latency_ms: int | None = None,
        p95_latency_ms: int | None = None,
        recording_key: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "duration_sec": duration_sec,
            "end_reason": end_reason,
            "ended_at": datetime.now(UTC).isoformat(),
            "transport": transport,
            "tts_provider": tts_provider,
            "llm_model": llm_model,
            "recording_key": recording_key,
        }
        if latency_stats is not None:
            payload["latency"] = {
                "stats": latency_stats,
                "avg_latency_ms": avg_latency_ms,
                "p95_latency_ms": p95_latency_ms,
            }
        await self._post_with_retry(f"/internal/calls/{call_id}/complete", payload)

    async def aclose(self) -> None:
        await self._client.aclose()


class EventReporter:
    """Batches call_events and flushes them in the background so reporting
    never blocks the voice pipeline. Fire-and-forget with bounded retry
    (see BOLApiClient._post_with_retry); events are dropped, not the call,
    if the API is unreachable.
    """

    def __init__(self, api: BOLApiClient, call_id: str | None, flush_interval_sec: float = 2.0):
        self._api = api
        self._call_id = call_id
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._flush_interval = flush_interval_sec
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if self._call_id is None:
            logger.warning("EventReporter started with no call_id — events will be logged only")
        self._task = asyncio.create_task(self._run())

    def report(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "ts": datetime.now(UTC).isoformat(),
            "type": event_type,
            "payload": payload,
        }
        if self._call_id is None:
            logger.info("call_event (no call_id, not sent): %s", event)
            return
        self._queue.put_nowait(event)

    async def _run(self) -> None:
        # Stopped via _stop_event rather than task.cancel() — cancelling
        # while a flush is mid-flight (inside _post_with_retry's own
        # sleeps/HTTP calls) would drop events already popped off the queue
        # for that flush. Waiting on the event instead means the loop only
        # ever stops between flushes, and always does one last flush before
        # exiting so nothing queued right before shutdown is skipped.
        while True:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._flush_interval)
            except TimeoutError:
                pass
            try:
                await self._flush()
            except Exception:
                logger.exception("EventReporter flush cycle failed; those events are lost")
            if self._stop_event.is_set():
                return

    async def _flush(self) -> None:
        events: list[dict[str, Any]] = []
        while not self._queue.empty():
            events.append(self._queue.get_nowait())
        if events and self._call_id is not None:
            await self._api.report_events(self._call_id, events)

    async def stop_and_flush(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._flush()
