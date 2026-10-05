import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.config import settings
from app.models.call import Call, CallDirection, CallStatus
from app.services.livekit_service import get_livekit_service
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


class FakeLiveKitService:
    def __init__(self, fail_on: str | None = None):
        self.fail_on = fail_on
        self.created_rooms: list[tuple] = []
        self.dialed: list[tuple] = []
        self.deleted_rooms: list[str] = []
        self.closed = False

    async def create_call_room(self, room_name, call_id, agent_id, transport=None):
        if self.fail_on == "create_call_room":
            raise RuntimeError("boom")
        self.created_rooms.append((room_name, call_id, agent_id, transport))

    async def dial_outbound(self, room_name, to_number, from_trunk_id=None, from_number=None):
        if self.fail_on == "dial_outbound":
            raise RuntimeError("boom")
        self.dialed.append((room_name, to_number, from_trunk_id, from_number))

    def generate_listen_token(self, room_name, identity, name):
        if self.fail_on == "generate_listen_token":
            raise RuntimeError("boom")
        return f"listen-token-for-{room_name}"

    async def delete_room(self, room_name):
        self.deleted_rooms.append(room_name)

    async def aclose(self):
        self.closed = True


@pytest.fixture
def fake_livekit():
    return FakeLiveKitService()


@pytest.fixture(autouse=True)
def _override_livekit(app, fake_livekit):
    app.dependency_overrides[get_livekit_service] = lambda: fake_livekit


async def _setup_agent_and_number(client, email="calls@acme-BOL.com"):
    headers = await register_and_login(client, "Acme", email)
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent_id = resp.json()["id"]
    resp = await client.post("/phone_numbers", json={"e164": "+15550001111"}, headers=headers)
    number_id = resp.json()["id"]
    return headers, agent_id, number_id


async def test_outbound_call_happy_path(client, fake_livekit):
    headers, agent_id, _ = await _setup_agent_and_number(client)

    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    call = resp.json()
    assert call["status"] == "ringing"
    assert call["direction"] == "outbound"
    assert call["to_number"] == "+15559998888"
    assert call["from_number"] == "+15550001111"
    assert call["livekit_room_name"] == f"BOL-call-{call['id']}"

    assert len(fake_livekit.created_rooms) == 1
    assert len(fake_livekit.dialed) == 1
    assert fake_livekit.dialed[0] == (
        call["livekit_room_name"],
        "+15559998888",
        None,
        "+15550001111",
    )


async def test_outbound_call_uses_number_own_trunk(client, fake_livekit):
    """A phone number with its own livekit_trunk_id (e.g. a Twilio number
    alongside Telnyx numbers) must dial through that trunk, not the
    platform-wide default — this is what lets multiple carriers coexist."""
    headers = await register_and_login(client, "Acme", "twiliocarrier@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent_id = resp.json()["id"]
    resp = await client.post(
        "/phone_numbers",
        json={
            "e164": "+15550003333",
            "provider": "twilio",
            "livekit_trunk_id": "ST_twilio_trunk",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    call = resp.json()

    assert fake_livekit.dialed[0] == (
        call["livekit_room_name"],
        "+15559998888",
        "ST_twilio_trunk",
        "+15550003333",
    )


async def test_outbound_call_unknown_agent_rejected(client):
    headers, _, _ = await _setup_agent_and_number(client, "unknownagent@acme-BOL.com")
    resp = await client.post(
        "/calls/outbound",
        json={
            "agent_id": "00000000-0000-0000-0000-000000000000",
            "to_number": "+15559998888",
        },
        headers=headers,
    )
    assert resp.status_code == 400


async def test_outbound_call_inactive_agent_rejected(client):
    headers = await register_and_login(client, "Acme", "inactive@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent_id = resp.json()["id"]
    await client.patch(f"/agents/{agent_id}", json={"is_active": False}, headers=headers)
    await client.post("/phone_numbers", json={"e164": "+15550002222"}, headers=headers)

    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )
    assert resp.status_code == 400


async def test_outbound_call_without_phone_number_rejected(client):
    headers = await register_and_login(client, "Acme", "nonumber@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent_id = resp.json()["id"]

    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "phone number" in resp.json()["detail"].lower()


async def test_outbound_call_respects_concurrency_cap(client, monkeypatch):
    monkeypatch.setattr(settings, "max_concurrent_calls", 1)
    headers, agent_id, _ = await _setup_agent_and_number(client, "concurrency@acme-BOL.com")

    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )
    assert resp.status_code == 201

    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559997777"},
        headers=headers,
    )
    assert resp.status_code == 429


async def test_outbound_call_respects_per_provider_concurrency_cap(client, monkeypatch):
    monkeypatch.setattr(settings, "fish_max_concurrent_calls", 1)
    headers = await register_and_login(client, "Acme", "provider-cap@acme-BOL.com")
    fish_payload = {**AGENT_PAYLOAD, "config": {**AGENT_PAYLOAD["config"], "tts_provider": "fish"}}
    resp = await client.post("/agents", json=fish_payload, headers=headers)
    agent_id = resp.json()["id"]
    await client.post("/phone_numbers", json={"e164": "+15550001111"}, headers=headers)

    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )
    assert resp.status_code == 201

    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559997777"},
        headers=headers,
    )
    assert resp.status_code == 429
    assert "fish" in resp.json()["detail"].lower()


async def test_outbound_call_provider_cap_is_platform_wide_not_per_org(client, monkeypatch):
    monkeypatch.setattr(settings, "fish_max_concurrent_calls", 1)
    fish_config = {**AGENT_PAYLOAD["config"], "tts_provider": "fish"}
    fish_payload = {**AGENT_PAYLOAD, "config": fish_config}

    headers_a = await register_and_login(client, "Acme", "provider-cap-a@acme-BOL.com")
    resp = await client.post("/agents", json=fish_payload, headers=headers_a)
    agent_a = resp.json()["id"]
    await client.post("/phone_numbers", json={"e164": "+15550001111"}, headers=headers_a)
    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_a, "to_number": "+15559998888"},
        headers=headers_a,
    )
    assert resp.status_code == 201

    headers_b = await register_and_login(client, "Beta", "provider-cap-b@beta-BOL.com")
    resp = await client.post("/agents", json=fish_payload, headers=headers_b)
    agent_b = resp.json()["id"]
    await client.post("/phone_numbers", json={"e164": "+15550002222"}, headers=headers_b)
    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_b, "to_number": "+15559997777"},
        headers=headers_b,
    )
    assert resp.status_code == 429


async def test_call_response_exposes_has_recording_not_the_raw_key(
    client, db_session_factory
):
    headers, agent_id, _ = await _setup_agent_and_number(client, "recording1@acme-BOL.com")
    resp = await client.get("/agents", headers=headers)
    org_id = uuid.UUID(resp.json()[0]["org_id"])

    async with db_session_factory() as session:
        call = Call(
            org_id=org_id,
            agent_id=uuid.UUID(agent_id),
            direction=CallDirection.outbound,
            to_number="+15551110000",
            from_number="+15550001111",
            status=CallStatus.completed,
            recording_key="recordings/some-call.ogg",
        )
        session.add(call)
        await session.commit()
        await session.refresh(call)
        call_id = call.id

    resp = await client.get("/calls", headers=headers)
    body = next(c for c in resp.json() if c["id"] == str(call_id))
    assert body["has_recording"] is True
    assert "recording_key" not in body
    assert "recording_url" not in body


async def test_get_recording_404s_without_a_recording(client, db_session_factory):
    headers, agent_id, _ = await _setup_agent_and_number(client, "recording2@acme-BOL.com")
    resp = await client.get("/agents", headers=headers)
    org_id = uuid.UUID(resp.json()[0]["org_id"])

    async with db_session_factory() as session:
        call = Call(
            org_id=org_id,
            agent_id=uuid.UUID(agent_id),
            direction=CallDirection.outbound,
            to_number="+15551110000",
            from_number="+15550001111",
            status=CallStatus.completed,
        )
        session.add(call)
        await session.commit()
        await session.refresh(call)
        call_id = call.id

    resp = await client.get(f"/calls/{call_id}/recording", headers=headers)
    assert resp.status_code == 404


async def test_get_recording_503s_when_s3_not_configured(client, db_session_factory, monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket", "")
    headers, agent_id, _ = await _setup_agent_and_number(client, "recording3@acme-BOL.com")
    resp = await client.get("/agents", headers=headers)
    org_id = uuid.UUID(resp.json()[0]["org_id"])

    async with db_session_factory() as session:
        call = Call(
            org_id=org_id,
            agent_id=uuid.UUID(agent_id),
            direction=CallDirection.outbound,
            to_number="+15551110000",
            from_number="+15550001111",
            status=CallStatus.completed,
            recording_key="recordings/some-call.ogg",
        )
        session.add(call)
        await session.commit()
        await session.refresh(call)
        call_id = call.id

    resp = await client.get(f"/calls/{call_id}/recording", headers=headers)
    assert resp.status_code == 503


async def test_get_recording_returns_presigned_url_when_configured(
    client, db_session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "s3_bucket", "BOL-recordings")
    monkeypatch.setattr(settings, "s3_access_key_id", "test-key")
    monkeypatch.setattr(settings, "s3_secret_access_key", "test-secret")
    headers, agent_id, _ = await _setup_agent_and_number(client, "recording4@acme-BOL.com")
    resp = await client.get("/agents", headers=headers)
    org_id = uuid.UUID(resp.json()[0]["org_id"])

    async with db_session_factory() as session:
        call = Call(
            org_id=org_id,
            agent_id=uuid.UUID(agent_id),
            direction=CallDirection.outbound,
            to_number="+15551110000",
            from_number="+15550001111",
            status=CallStatus.completed,
            recording_key="recordings/some-call.ogg",
        )
        session.add(call)
        await session.commit()
        await session.refresh(call)
        call_id = call.id

    resp = await client.get(f"/calls/{call_id}/recording", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "BOL-recordings" in body["url"]
    assert "recordings/some-call.ogg" in body["url"]


async def test_listen_to_active_call_returns_subscriber_token(client, fake_livekit):
    headers, agent_id, _ = await _setup_agent_and_number(client, "listen1@acme-BOL.com")
    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )
    call_id = resp.json()["id"]

    resp = await client.get(f"/calls/{call_id}/listen", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["room_name"] == f"BOL-call-{call_id}"
    assert body["token"] == f"listen-token-for-BOL-call-{call_id}"


async def test_listen_to_inactive_call_rejected(client, db_session_factory):
    headers, agent_id, _ = await _setup_agent_and_number(client, "listen2@acme-BOL.com")
    resp = await client.get("/agents", headers=headers)
    org_id = uuid.UUID(resp.json()[0]["org_id"])

    async with db_session_factory() as session:
        call = Call(
            org_id=org_id,
            agent_id=uuid.UUID(agent_id),
            direction=CallDirection.outbound,
            to_number="+15551110000",
            from_number="+15550001111",
            status=CallStatus.completed,
            livekit_room_name="BOL-call-done",
        )
        session.add(call)
        await session.commit()
        await session.refresh(call)
        call_id = call.id

    resp = await client.get(f"/calls/{call_id}/listen", headers=headers)
    assert resp.status_code == 400


async def test_listen_to_unknown_call_404s(client):
    headers, _, _ = await _setup_agent_and_number(client, "listen3@acme-BOL.com")
    resp = await client.get(f"/calls/{uuid.uuid4()}/listen", headers=headers)
    assert resp.status_code == 404


async def test_provider_concurrency_check_reaps_stale_calls_across_every_org(
    client, db_session_factory, monkeypatch
):
    # The provider-concurrency check is platform-wide (it guards a shared
    # Fish/Chatterbox capacity, not a per-org one) — a stale call from org A
    # must not permanently block org B just because org B never happens to
    # trigger org A's own reap.
    monkeypatch.setattr(settings, "fish_max_concurrent_calls", 1)
    fish_config = {**AGENT_PAYLOAD["config"], "tts_provider": "fish"}
    fish_payload = {**AGENT_PAYLOAD, "config": fish_config}

    headers_a = await register_and_login(client, "Acme", "platformreap-a@acme-BOL.com")
    resp = await client.post("/agents", json=fish_payload, headers=headers_a)
    agent_a = resp.json()["id"]
    org_a = uuid.UUID(resp.json()["org_id"])

    async with db_session_factory() as session:
        stale = Call(
            org_id=org_a,
            agent_id=uuid.UUID(agent_a),
            direction=CallDirection.outbound,
            to_number="+15551110000",
            from_number="+15550001111",
            status=CallStatus.ringing,
            tts_provider="fish",
            created_at=datetime.now(UTC) - timedelta(seconds=900),
        )
        session.add(stale)
        await session.commit()

    headers_b = await register_and_login(client, "Beta", "platformreap-b@beta-BOL.com")
    resp = await client.post("/agents", json=fish_payload, headers=headers_b)
    agent_b = resp.json()["id"]
    await client.post("/phone_numbers", json={"e164": "+15550002222"}, headers=headers_b)

    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_b, "to_number": "+15559997777"},
        headers=headers_b,
    )
    assert resp.status_code == 201, resp.text


async def test_stale_call_is_reaped_and_frees_concurrency_slot(
    client, db_session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "max_concurrent_calls", 1)
    headers, agent_id, _ = await _setup_agent_and_number(client, "reaper1@acme-BOL.com")
    resp = await client.get("/agents", headers=headers)
    org_id = uuid.UUID(resp.json()[0]["org_id"])

    # A worker that died before ever calling /complete: stuck at "ringing"
    # long past its agent's max_call_duration_sec (600s default) + grace.
    async with db_session_factory() as session:
        stale = Call(
            org_id=org_id,
            agent_id=uuid.UUID(agent_id),
            direction=CallDirection.outbound,
            to_number="+15551110000",
            from_number="+15550001111",
            status=CallStatus.ringing,
            created_at=datetime.now(UTC) - timedelta(seconds=900),
        )
        session.add(stale)
        await session.commit()
        await session.refresh(stale)
        stale_id = stale.id

    # Without reaping, this org already has 1 active (stale) call and the
    # cap is 1 — this request should still succeed because creating an
    # outbound call reaps stale calls before checking the cap.
    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    async with db_session_factory() as session:
        refreshed = await session.get(Call, stale_id)
        assert refreshed.status == CallStatus.failed
        assert refreshed.end_reason == "worker_lost"


async def test_recent_active_call_is_not_reaped(client, db_session_factory):
    headers, agent_id, _ = await _setup_agent_and_number(client, "reaper2@acme-BOL.com")
    resp = await client.get("/agents", headers=headers)
    org_id = uuid.UUID(resp.json()[0]["org_id"])

    async with db_session_factory() as session:
        recent = Call(
            org_id=org_id,
            agent_id=uuid.UUID(agent_id),
            direction=CallDirection.outbound,
            to_number="+15551110000",
            from_number="+15550001111",
            status=CallStatus.ringing,
        )
        session.add(recent)
        await session.commit()
        await session.refresh(recent)
        recent_id = recent.id

    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )
    assert resp.status_code == 201

    async with db_session_factory() as session:
        refreshed = await session.get(Call, recent_id)
        assert refreshed.status == CallStatus.ringing


async def test_outbound_call_marks_failed_on_dispatch_error(client, app):
    failing_livekit = FakeLiveKitService(fail_on="dial_outbound")
    app.dependency_overrides[get_livekit_service] = lambda: failing_livekit

    headers, agent_id, _ = await _setup_agent_and_number(client, "dispatchfail@acme-BOL.com")
    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )
    assert resp.status_code == 502

    resp = await client.get("/calls", headers=headers)
    calls = resp.json()
    assert len(calls) == 1
    assert calls[0]["status"] == "failed"
    assert calls[0]["end_reason"] == "dispatch_failed"


async def test_list_calls_filters_by_status_and_direction(client):
    headers, agent_id, _ = await _setup_agent_and_number(client, "filters@acme-BOL.com")
    await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )

    resp = await client.get("/calls?status=ringing&direction=outbound", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = await client.get("/calls?status=completed", headers=headers)
    assert resp.json() == []


async def test_get_call_detail_includes_events(client):
    headers, agent_id, _ = await _setup_agent_and_number(client, "detail@acme-BOL.com")
    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )
    call_id = resp.json()["id"]

    internal_headers = {"Authorization": f"Bearer {settings.internal_service_token}"}
    await client.post(
        f"/internal/calls/{call_id}/events",
        json={
            "events": [
                {
                    "ts": "2026-08-15T12:00:00Z",
                    "type": "transcript_agent",
                    "payload": {"text": "Hello!"},
                }
            ]
        },
        headers=internal_headers,
    )

    resp = await client.get(f"/calls/{call_id}", headers=headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert len(detail["events"]) == 1
    assert detail["events"][0]["payload"]["text"] == "Hello!"


async def test_hangup_call_deletes_room_and_completes(client, fake_livekit):
    headers, agent_id, _ = await _setup_agent_and_number(client, "hangup@acme-BOL.com")
    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )
    call = resp.json()

    resp = await client.post(f"/calls/{call['id']}/hangup", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["end_reason"] == "operator_hangup"
    assert fake_livekit.deleted_rooms == [call["livekit_room_name"]]


async def test_hangup_already_completed_call_rejected(client):
    headers, agent_id, _ = await _setup_agent_and_number(client, "doublehangup@acme-BOL.com")
    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )
    call_id = resp.json()["id"]
    await client.post(f"/calls/{call_id}/hangup", headers=headers)

    resp = await client.post(f"/calls/{call_id}/hangup", headers=headers)
    assert resp.status_code == 400


async def test_cross_org_call_access_is_blocked(client):
    headers_a, agent_id, _ = await _setup_agent_and_number(client, "orga@a-BOL.com")
    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers_a,
    )
    call_id = resp.json()["id"]

    headers_b = await register_and_login(client, "Org B", "orgb@b-BOL.com")
    resp = await client.get(f"/calls/{call_id}", headers=headers_b)
    assert resp.status_code == 404

    resp = await client.post(f"/calls/{call_id}/hangup", headers=headers_b)
    assert resp.status_code == 404

    resp = await client.get("/calls", headers=headers_b)
    assert resp.json() == []
