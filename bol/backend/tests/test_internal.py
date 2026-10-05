import uuid
from datetime import UTC, datetime

import pytest

from app.config import settings
from app.models.call import Call, CallDirection, CallStatus
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
    },
    "tools": [],
}

INTERNAL_HEADERS = {"Authorization": f"Bearer {settings.internal_service_token}"}


async def _create_call(db_session_factory, org_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    async with db_session_factory() as session:
        call = Call(
            org_id=org_id,
            agent_id=agent_id,
            direction=CallDirection.outbound,
            to_number="+15551234567",
            from_number="+15557654321",
            status=CallStatus.in_progress,
        )
        session.add(call)
        await session.commit()
        await session.refresh(call)
        return call.id


async def test_internal_endpoints_require_service_token(client):
    resp = await client.get(f"/internal/agents/{uuid.uuid4()}")
    assert resp.status_code == 401

    resp = await client.get(
        f"/internal/agents/{uuid.uuid4()}", headers={"Authorization": "Bearer wrong-token"}
    )
    assert resp.status_code == 401


async def test_worker_can_fetch_agent_config(client):
    headers = await register_and_login(client, "Acme", "worker1@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent_id = resp.json()["id"]

    # No user-org scoping on the internal route — it's authenticated by service token only.
    resp = await client.get(f"/internal/agents/{agent_id}", headers=INTERNAL_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["config"]["system_prompt"] == "You are a helpful receptionist."


async def test_internal_agent_not_found(client):
    resp = await client.get(f"/internal/agents/{uuid.uuid4()}", headers=INTERNAL_HEADERS)
    assert resp.status_code == 404


@pytest.mark.usefixtures("db_session_factory")
async def test_worker_can_report_events_and_complete_call(client, db_session_factory):
    headers = await register_and_login(client, "Acme", "worker2@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent = resp.json()
    org_id = uuid.UUID(agent["org_id"])
    agent_id = uuid.UUID(agent["id"])

    call_id = await _create_call(db_session_factory, org_id, agent_id)

    resp = await client.post(
        f"/internal/calls/{call_id}/events",
        json={
            "events": [
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "type": "transcript_user",
                    "payload": {"text": "Hello, is anyone there?"},
                },
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "type": "transcript_agent",
                    "payload": {"text": "Hi! How can I help you today?"},
                },
            ]
        },
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 204

    resp = await client.post(
        f"/internal/calls/{call_id}/complete",
        json={"duration_sec": 42, "end_reason": "caller_hangup"},
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 204

    async with db_session_factory() as session:
        refreshed = await session.get(Call, call_id)
        assert refreshed.status == CallStatus.completed
        assert refreshed.duration_sec == 42
        assert refreshed.end_reason == "caller_hangup"


async def test_complete_call_stores_recording_key(client, db_session_factory):
    headers = await register_and_login(client, "Acme", "recordingkey1@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent = resp.json()
    org_id = uuid.UUID(agent["org_id"])
    agent_id = uuid.UUID(agent["id"])
    call_id = await _create_call(db_session_factory, org_id, agent_id)

    resp = await client.post(
        f"/internal/calls/{call_id}/complete",
        json={
            "duration_sec": 42,
            "end_reason": "caller_hangup",
            "recording_key": "recordings/abc.ogg",
        },
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 204

    async with db_session_factory() as session:
        refreshed = await session.get(Call, call_id)
        assert refreshed.recording_key == "recordings/abc.ogg"


async def test_mark_call_answered_sets_in_progress_and_answered_at(client, db_session_factory):
    headers = await register_and_login(client, "Acme", "answered1@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent = resp.json()

    async with db_session_factory() as session:
        call = Call(
            org_id=uuid.UUID(agent["org_id"]),
            agent_id=uuid.UUID(agent["id"]),
            direction=CallDirection.outbound,
            to_number="+15551234567",
            from_number="+15557654321",
            status=CallStatus.ringing,
        )
        session.add(call)
        await session.commit()
        await session.refresh(call)
        call_id = call.id

    resp = await client.post(f"/internal/calls/{call_id}/answered", headers=INTERNAL_HEADERS)
    assert resp.status_code == 204

    async with db_session_factory() as session:
        refreshed = await session.get(Call, call_id)
        assert refreshed.status == CallStatus.in_progress
        assert refreshed.answered_at is not None


async def test_mark_unknown_call_answered_404s(client):
    resp = await client.post(
        f"/internal/calls/{uuid.uuid4()}/answered", headers=INTERNAL_HEADERS
    )
    assert resp.status_code == 404


@pytest.mark.parametrize(
    ("end_reason", "expected_status"),
    [
        ("no_answer", CallStatus.no_answer),
        ("busy", CallStatus.busy),
        ("dispatch_failed", CallStatus.failed),
        ("worker_lost", CallStatus.failed),
        ("caller_hangup", CallStatus.completed),
        ("agent_ended_call", CallStatus.completed),
    ],
)
async def test_complete_call_maps_end_reason_to_status(
    client, db_session_factory, end_reason, expected_status
):
    headers = await register_and_login(client, "Acme", f"complete-{end_reason}@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent = resp.json()
    call_id = await _create_call(
        db_session_factory, uuid.UUID(agent["org_id"]), uuid.UUID(agent["id"])
    )

    resp = await client.post(
        f"/internal/calls/{call_id}/complete",
        json={"duration_sec": 5, "end_reason": end_reason},
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 204

    async with db_session_factory() as session:
        refreshed = await session.get(Call, call_id)
        assert refreshed.status == expected_status


async def test_complete_call_unpacks_latency_and_provider_fields(client, db_session_factory):
    headers = await register_and_login(client, "Acme", "latencycomplete@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent = resp.json()
    call_id = await _create_call(
        db_session_factory, uuid.UUID(agent["org_id"]), uuid.UUID(agent["id"])
    )

    resp = await client.post(
        f"/internal/calls/{call_id}/complete",
        json={
            "duration_sec": 30,
            "end_reason": "caller_hangup",
            "transport": "telephony",
            "tts_provider": "fish",
            "llm_model": "qwen/qwen3.6-27b",
            "latency": {
                "stats": {"turn_count": 3, "stages": {"e2e_latency": {"avg": 0.8}}},
                "avg_latency_ms": 800,
                "p95_latency_ms": 1200,
            },
        },
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 204

    async with db_session_factory() as session:
        refreshed = await session.get(Call, call_id)
        assert refreshed.transport == "telephony"
        assert refreshed.tts_provider == "fish"
        assert refreshed.llm_model == "qwen/qwen3.6-27b"
        assert refreshed.avg_latency_ms == 800
        assert refreshed.p95_latency_ms == 1200
        assert refreshed.latency_stats["turn_count"] == 3

    resp = await client.get(f"/calls/{call_id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["avg_latency_ms"] == 800
    assert body["latency_stats"]["turn_count"] == 3


async def test_complete_call_without_latency_leaves_it_null(client, db_session_factory):
    # A worker that crashed before resolving the pipeline still needs to be
    # able to report *something* completed — latency must be optional.
    headers = await register_and_login(client, "Acme", "nolatency@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent = resp.json()
    call_id = await _create_call(
        db_session_factory, uuid.UUID(agent["org_id"]), uuid.UUID(agent["id"])
    )

    resp = await client.post(
        f"/internal/calls/{call_id}/complete",
        json={"duration_sec": 5, "end_reason": "agent_config_fetch_failed"},
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 204

    async with db_session_factory() as session:
        refreshed = await session.get(Call, call_id)
        assert refreshed.status == CallStatus.failed
        assert refreshed.latency_stats is None
        assert refreshed.avg_latency_ms is None


async def test_report_events_for_unknown_call_404s(client):
    resp = await client.post(
        f"/internal/calls/{uuid.uuid4()}/events",
        json={"events": []},
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 404


async def test_complete_unknown_call_404s(client):
    resp = await client.post(
        f"/internal/calls/{uuid.uuid4()}/complete",
        json={"duration_sec": 1, "end_reason": "x"},
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 404


async def test_inbound_call_creation_resolves_number_and_creates_call(client):
    headers = await register_and_login(client, "Acme", "inbound1@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent_id = resp.json()["id"]
    resp = await client.post(
        "/phone_numbers",
        json={"e164": "+15551112222", "inbound_agent_id": agent_id},
        headers=headers,
    )
    assert resp.status_code == 201

    resp = await client.post(
        "/internal/calls/inbound",
        json={
            "to_number": "+15551112222",
            "from_number": "+15559998888",
            "livekit_room_name": "BOL-inbound-abc123",
        },
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["agent_id"] == agent_id

    # The caller has no user session for this call — but as the org owner we can
    # still see it landed correctly via the public API.
    resp = await client.get(f"/calls/{body['call_id']}", headers=headers)
    assert resp.status_code == 200
    call = resp.json()
    assert call["direction"] == "inbound"
    assert call["status"] == "in_progress"
    assert call["from_number"] == "+15559998888"
    assert call["livekit_room_name"] == "BOL-inbound-abc123"


async def test_inbound_call_unknown_number_404s(client):
    resp = await client.post(
        "/internal/calls/inbound",
        json={
            "to_number": "+15550000000",
            "from_number": "+15559998888",
            "livekit_room_name": "BOL-inbound-xyz",
        },
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 404


async def test_inbound_call_number_without_agent_conflicts(client):
    headers = await register_and_login(client, "Acme", "inbound2@acme-BOL.com")
    resp = await client.post("/phone_numbers", json={"e164": "+15553334444"}, headers=headers)
    assert resp.status_code == 201

    resp = await client.post(
        "/internal/calls/inbound",
        json={
            "to_number": "+15553334444",
            "from_number": "+15559998888",
            "livekit_room_name": "BOL-inbound-noagent",
        },
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 409
