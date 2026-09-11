"""HTTP client the worker uses to talk to the API. The worker never touches the DB directly."""
import os
from typing import Any

import httpx

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
INTERNAL_SERVICE_TOKEN = os.environ.get("INTERNAL_SERVICE_TOKEN", "change-me")

_headers = {"X-Service-Token": INTERNAL_SERVICE_TOKEN}


async def get_agent_config(agent_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=10.0) as client:
        resp = await client.get(f"/internal/agents/{agent_id}", headers=_headers)
        resp.raise_for_status()
        return resp.json()


async def report_event(call_id: str, event_type: str, payload: dict[str, Any]) -> None:
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=10.0) as client:
        resp = await client.post(
            f"/internal/calls/{call_id}/events",
            headers=_headers,
            json={"type": event_type, "payload": payload},
        )
        resp.raise_for_status()


async def complete_call(call_id: str, duration_sec: int, end_reason: str) -> None:
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=10.0) as client:
        resp = await client.post(
            f"/internal/calls/{call_id}/complete",
            headers=_headers,
            json={"duration_sec": duration_sec, "end_reason": end_reason},
        )
        resp.raise_for_status()
