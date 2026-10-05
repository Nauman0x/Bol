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


async def test_agent_accepts_any_iso_language_code(client):
    headers = await register_and_login(client, "Acme", "lang1@acme-BOL.com")
    for lang in ("es", "fr", "hi", "ur", "zh", "auto"):
        payload = {**AGENT_PAYLOAD, "config": {**AGENT_PAYLOAD["config"], "language": lang}}
        resp = await client.post("/agents", json=payload, headers=headers)
        assert resp.status_code == 201, (lang, resp.text)
        assert resp.json()["config"]["language"] == lang


async def test_agent_rejects_invalid_language_code(client):
    headers = await register_and_login(client, "Acme", "lang2@acme-BOL.com")
    for bad in ("english", "en-US", "123", ""):
        payload = {**AGENT_PAYLOAD, "config": {**AGENT_PAYLOAD["config"], "language": bad}}
        resp = await client.post("/agents", json=payload, headers=headers)
        assert resp.status_code == 422, bad


async def test_agent_normalizes_language_case(client):
    headers = await register_and_login(client, "Acme", "lang3@acme-BOL.com")
    payload = {**AGENT_PAYLOAD, "config": {**AGENT_PAYLOAD["config"], "language": "ES"}}
    resp = await client.post("/agents", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["config"]["language"] == "es"


async def test_agent_crud_flow(client):
    headers = await register_and_login(client, "Acme", "owner@acme-BOL.com")

    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    assert resp.status_code == 201, resp.text
    agent = resp.json()
    agent_id = agent["id"]

    resp = await client.get("/agents", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = await client.get(f"/agents/{agent_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "BOL Receptionist"

    resp = await client.patch(
        f"/agents/{agent_id}", json={"name": "Updated Name"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"

    resp = await client.delete(f"/agents/{agent_id}", headers=headers)
    assert resp.status_code == 204

    resp = await client.get(f"/agents/{agent_id}", headers=headers)
    assert resp.status_code == 404


async def test_agent_config_validation_rejects_bad_temperature(client):
    headers = await register_and_login(client, "Acme", "validator@acme-BOL.com")
    bad_payload = {**AGENT_PAYLOAD, "config": {**AGENT_PAYLOAD["config"], "temperature": 5.0}}
    resp = await client.post("/agents", json=bad_payload, headers=headers)
    assert resp.status_code == 422


async def test_agent_rejects_unknown_interruption_style(client):
    headers = await register_and_login(client, "Acme", "interrupt1@acme-BOL.com")
    bad_payload = {
        **AGENT_PAYLOAD,
        "config": {**AGENT_PAYLOAD["config"], "interruption_style": "aggressive"},
    }
    resp = await client.post("/agents", json=bad_payload, headers=headers)
    assert resp.status_code == 422


async def test_agent_rejects_out_of_range_interruption_fields(client):
    headers = await register_and_login(client, "Acme", "interrupt2@acme-BOL.com")
    for field, bad_value in (
        ("interruption_min_duration", -1.0),
        ("interruption_min_duration", 10.0),
        ("interruption_min_words", -1),
        ("false_interruption_timeout", 0.01),
    ):
        payload = {**AGENT_PAYLOAD, "config": {**AGENT_PAYLOAD["config"], field: bad_value}}
        resp = await client.post("/agents", json=payload, headers=headers)
        assert resp.status_code == 422, (field, bad_value)


async def test_agent_with_no_interruption_keys_resolves_to_balanced(client):
    # AGENT_PAYLOAD predates these fields entirely — every field must default
    # rather than 422, and the persisted config must resolve (via
    # app.interruption.resolve_interruption) to today's historical behavior.
    from app.interruption import resolve_interruption

    headers = await register_and_login(client, "Acme", "interrupt3@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    assert resp.status_code == 201, resp.text
    config = resp.json()["config"]
    assert config["interruption_style"] == "balanced"
    assert resolve_interruption(config) == {
        "min_duration": 0.3,
        "min_words": 0,
        "false_interruption_timeout": 2.0,
    }


async def test_agent_adaptive_mode_allowed_even_when_stt_provider_cannot_support_it(
    client, monkeypatch
):
    # Deliberate policy: STT_PROVIDER is a deploy-time env var, not agent
    # data, so requesting adaptive mode is never a 422 — the worker
    # downgrades it at call time instead (see worker/pipeline.py). A 422
    # here would mean flipping STT_PROVIDER during an outage locks every
    # agent with mode="adaptive" out of being saved at all.
    from app.config import settings

    monkeypatch.setattr(settings, "stt_provider", "groq")
    headers = await register_and_login(client, "Acme", "interrupt4@acme-BOL.com")
    payload = {
        **AGENT_PAYLOAD,
        "config": {**AGENT_PAYLOAD["config"], "interruption_mode": "adaptive"},
    }
    resp = await client.post("/agents", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["config"]["interruption_mode"] == "adaptive"


async def test_cross_org_agent_access_is_blocked(client):
    headers_a = await register_and_login(client, "Org A", "a@a-BOL.com")
    headers_b = await register_and_login(client, "Org B", "b@b-BOL.com")

    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers_a)
    agent_id = resp.json()["id"]

    # Org B cannot read Org A's agent
    resp = await client.get(f"/agents/{agent_id}", headers=headers_b)
    assert resp.status_code == 404

    # Org B cannot see it in their list
    resp = await client.get("/agents", headers=headers_b)
    assert resp.json() == []

    # Org B cannot patch or delete it
    resp = await client.patch(f"/agents/{agent_id}", json={"name": "Hijacked"}, headers=headers_b)
    assert resp.status_code == 404
    resp = await client.delete(f"/agents/{agent_id}", headers=headers_b)
    assert resp.status_code == 404

    # Org A still sees it untouched
    resp = await client.get(f"/agents/{agent_id}", headers=headers_a)
    assert resp.status_code == 200
    assert resp.json()["name"] == "BOL Receptionist"


async def test_delete_agent_referenced_by_phone_number_clears_reference(client):
    headers = await register_and_login(client, "Acme", "numowner@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent_id = resp.json()["id"]

    resp = await client.post(
        "/phone_numbers",
        json={"e164": "+15551234567", "inbound_agent_id": agent_id},
        headers=headers,
    )
    assert resp.status_code == 201

    resp = await client.delete(f"/agents/{agent_id}", headers=headers)
    assert resp.status_code == 204

    resp = await client.get("/phone_numbers", headers=headers)
    assert resp.json()[0]["inbound_agent_id"] is None


class FakeLiveKitService:
    def __init__(self, fail=False, fail_token=False):
        self.fail = fail
        self.fail_token = fail_token
        self.created_rooms = []
        self.deleted_rooms = []

    async def create_call_room(self, room_name, call_id, agent_id, transport=None):
        if self.fail:
            raise RuntimeError("boom")
        self.created_rooms.append((room_name, call_id, agent_id, transport))

    def generate_join_token(self, room_name, identity, name):
        if self.fail_token:
            raise RuntimeError("boom")
        return f"fake-token-for-{identity}-in-{room_name}"

    async def delete_room(self, room_name):
        self.deleted_rooms.append(room_name)

    async def aclose(self):
        pass


async def test_create_test_session_returns_joinable_token(client, app):
    fake = FakeLiveKitService()
    app.dependency_overrides[get_livekit_service] = lambda: fake

    headers = await register_and_login(client, "Acme", "testsession@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent_id = resp.json()["id"]

    resp = await client.post(f"/agents/{agent_id}/test-session", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["room_name"].startswith(f"BOL-test-{agent_id}")
    assert body["token"]
    assert body["call_id"]
    assert len(fake.created_rooms) == 1
    # A real Call row now backs every test session (direction="test"), so
    # its transcript/latency are tracked the same as any other call.
    assert str(fake.created_rooms[0][1]) == body["call_id"]
    assert fake.created_rooms[0][3] == "webrtc"

    calls_resp = await client.get("/calls", headers=headers)
    assert calls_resp.status_code == 200
    call = next(c for c in calls_resp.json() if c["id"] == body["call_id"])
    assert call["direction"] == "test"
    assert call["transport"] == "webrtc"


async def test_create_test_session_for_unknown_agent_404s(client):
    headers = await register_and_login(client, "Acme", "testsession404@acme-BOL.com")
    resp = await client.post(
        "/agents/00000000-0000-0000-0000-000000000000/test-session", headers=headers
    )
    assert resp.status_code == 404


async def test_create_test_session_dispatch_failure_502s(client, app):
    fake = FakeLiveKitService(fail=True)
    app.dependency_overrides[get_livekit_service] = lambda: fake

    headers = await register_and_login(client, "Acme", "testsessionfail@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent_id = resp.json()["id"]

    resp = await client.post(f"/agents/{agent_id}/test-session", headers=headers)
    assert resp.status_code == 502


async def test_create_test_session_token_failure_cleans_up_orphaned_room(client, app):
    # create_call_room succeeds (room now has an agent dispatch attached)
    # but generate_join_token then fails — the room must not be left behind.
    fake = FakeLiveKitService(fail_token=True)
    app.dependency_overrides[get_livekit_service] = lambda: fake

    headers = await register_and_login(client, "Acme", "testsessiontokenfail@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent_id = resp.json()["id"]

    resp = await client.post(f"/agents/{agent_id}/test-session", headers=headers)
    assert resp.status_code == 502
    assert len(fake.created_rooms) == 1
    assert fake.deleted_rooms == [fake.created_rooms[0][0]]
