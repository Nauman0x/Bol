"""Covers the two side effects internal.py's complete_call triggers as a
background task once a call reaches a terminal state: post-call LLM
analysis (app/services/call_analysis.py) and outbound webhook dispatch
(app/services/webhook_dispatch.py). Both run via BackgroundTasks — with the
ASGITransport test client, the background task completes before
client.post(...) returns (Starlette runs it inside the same response
lifecycle), so assertions right after the request are deterministic.
"""

import json
import uuid
from datetime import UTC, datetime

import httpx

from app.config import settings
from app.models.call import Call, CallDirection, CallStatus
from app.services.webhook_dispatch import SIGNATURE_HEADER, sign
from tests.conftest import register_and_login

AGENT_PAYLOAD = {
    "name": "BOL Receptionist",
    "config": {
        "system_prompt": "You are a helpful receptionist.",
        "greeting": "Hi there",
        "language": "en",
        "voice_id": "default",
        "llm_model": "qwen/qwen3.6-27b",
        "temperature": 0.7,
        "max_call_duration_sec": 600,
        "interruption_enabled": True,
        "analysis_schema": {"appointment_time": "the time the caller agreed to, or null"},
    },
    "tools": [],
}

INTERNAL_HEADERS = {"Authorization": f"Bearer {settings.internal_service_token}"}


class _FakeGroqClient:
    """Stand-in for httpx.AsyncClient — patched onto
    app.services.call_analysis.httpx.AsyncClient specifically."""

    def __init__(self, response_content: str):
        self._response_content = response_content

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": self._response_content}}]},
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        )


class _RecordingWebhookClient:
    """Stand-in for httpx.AsyncClient — patched onto
    app.services.webhook_dispatch.httpx.AsyncClient. Records every call made
    via post() so the test can assert on signature/payload."""

    calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, content, headers, **kwargs):
        type(self).calls.append({"url": url, "content": content, "headers": headers})
        return httpx.Response(200, request=httpx.Request("POST", url))


async def _create_call_with_transcript(client, db_session_factory, headers) -> uuid.UUID:
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent = resp.json()
    org_id = uuid.UUID(agent["org_id"])
    agent_id = uuid.UUID(agent["id"])

    async with db_session_factory() as session:
        call = Call(
            org_id=org_id,
            agent_id=agent_id,
            direction=CallDirection.outbound,
            to_number="+15551234567",
            from_number="+15557654321",
            status=CallStatus.in_progress,
            tts_provider="groq",
        )
        session.add(call)
        await session.commit()
        await session.refresh(call)
        call_id = call.id

    await client.post(
        f"/internal/calls/{call_id}/events",
        json={
            "events": [
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "type": "transcript_user",
                    "payload": {"text": "I'd like to book an appointment for 3pm."},
                },
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "type": "transcript_agent",
                    "payload": {"text": "Sure, 3pm works. See you then!"},
                },
            ]
        },
        headers=INTERNAL_HEADERS,
    )
    return call_id


async def test_complete_call_sets_cost_estimate(client, db_session_factory):
    headers = await register_and_login(client, "Acme", "effects1@acme-BOL.com")
    call_id = await _create_call_with_transcript(client, db_session_factory, headers)

    resp = await client.post(
        f"/internal/calls/{call_id}/complete",
        json={"duration_sec": 120, "end_reason": "caller_hangup", "transport": "telephony"},
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 204

    async with db_session_factory() as session:
        refreshed = await session.get(Call, call_id)
        assert refreshed.cost_estimate is not None
        assert refreshed.cost_estimate > 0


async def test_complete_call_runs_analysis_when_groq_configured(
    client, db_session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "groq_api_key", "gk_test")
    analysis_body = json.dumps(
        {
            "summary": "Caller booked a 3pm appointment.",
            "outcome": "resolved",
            "sentiment": "positive",
            "extracted": {"appointment_time": "3pm"},
        }
    )
    monkeypatch.setattr(
        "app.services.call_analysis.httpx.AsyncClient",
        lambda **kwargs: _FakeGroqClient(analysis_body),
    )

    headers = await register_and_login(client, "Acme", "effects2@acme-BOL.com")
    call_id = await _create_call_with_transcript(client, db_session_factory, headers)

    resp = await client.post(
        f"/internal/calls/{call_id}/complete",
        json={"duration_sec": 90, "end_reason": "caller_hangup"},
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 204

    async with db_session_factory() as session:
        refreshed = await session.get(Call, call_id)
        assert refreshed.analysis is not None
        assert refreshed.analysis["outcome"] == "resolved"
        assert refreshed.analysis["extracted"]["appointment_time"] == "3pm"


async def test_complete_call_skips_analysis_without_groq_key(
    client, db_session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "groq_api_key", "")

    headers = await register_and_login(client, "Acme", "effects3@acme-BOL.com")
    call_id = await _create_call_with_transcript(client, db_session_factory, headers)

    resp = await client.post(
        f"/internal/calls/{call_id}/complete",
        json={"duration_sec": 90, "end_reason": "caller_hangup"},
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 204

    async with db_session_factory() as session:
        refreshed = await session.get(Call, call_id)
        assert refreshed.analysis is None


async def test_complete_call_dispatches_signed_webhook(client, db_session_factory, monkeypatch):
    _RecordingWebhookClient.calls = []
    monkeypatch.setattr(
        "app.services.webhook_dispatch.httpx.AsyncClient",
        lambda **kwargs: _RecordingWebhookClient(),
    )

    headers = await register_and_login(client, "Acme", "effects4@acme-BOL.com")
    resp = await client.post(
        "/webhooks",
        json={"url": "https://example.com/hook", "events": ["call.completed"]},
        headers=headers,
    )
    secret = resp.json()["secret"]

    call_id = await _create_call_with_transcript(client, db_session_factory, headers)
    resp = await client.post(
        f"/internal/calls/{call_id}/complete",
        json={"duration_sec": 90, "end_reason": "caller_hangup"},
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 204

    assert len(_RecordingWebhookClient.calls) == 1
    delivered = _RecordingWebhookClient.calls[0]
    assert delivered["url"] == "https://example.com/hook"
    assert delivered["headers"][SIGNATURE_HEADER] == sign(secret, delivered["content"])
    body = json.loads(delivered["content"])
    assert body["event"] == "call.completed"
    assert body["data"]["call_id"] == str(call_id)
    assert body["data"]["status"] == "completed"


async def test_complete_call_with_no_webhooks_configured_dispatches_nothing(
    client, db_session_factory, monkeypatch
):
    _RecordingWebhookClient.calls = []
    monkeypatch.setattr(
        "app.services.webhook_dispatch.httpx.AsyncClient",
        lambda **kwargs: _RecordingWebhookClient(),
    )

    headers = await register_and_login(client, "Acme", "effects5@acme-BOL.com")

    call_id = await _create_call_with_transcript(client, db_session_factory, headers)
    resp = await client.post(
        f"/internal/calls/{call_id}/complete",
        json={"duration_sec": 90, "end_reason": "caller_hangup"},
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 204
    assert _RecordingWebhookClient.calls == []
