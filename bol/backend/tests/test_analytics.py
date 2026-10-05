import uuid

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


async def test_analytics_summary_empty_org(client):
    headers = await register_and_login(client, "Acme", "analytics1@acme-BOL.com")
    resp = await client.get("/analytics/summary", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_calls"] == 0
    assert body["answer_rate"] == 0
    assert body["calls_by_day"] == []


async def test_analytics_summary_counts_calls(client, app):
    from app.services.livekit_service import get_livekit_service

    class FakeLiveKit:
        async def create_call_room(self, *a, **k):
            pass

        async def dial_outbound(self, *a, **k):
            pass

        async def aclose(self):
            pass

    app.dependency_overrides[get_livekit_service] = lambda: FakeLiveKit()

    headers = await register_and_login(client, "Acme", "analytics2@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent_id = resp.json()["id"]
    await client.post("/phone_numbers", json={"e164": "+15550009999"}, headers=headers)

    resp = await client.post(
        "/calls/outbound",
        json={"agent_id": agent_id, "to_number": "+15559998888"},
        headers=headers,
    )
    assert resp.status_code == 201

    resp = await client.get("/analytics/summary", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_calls"] == 1
    assert len(body["calls_by_day"]) == 1
    assert body["calls_by_day"][0]["count"] == 1


async def test_analytics_summary_is_org_scoped(client):
    headers_a = await register_and_login(client, "Org A", "analyticsa@a-BOL.com")
    headers_b = await register_and_login(client, "Org B", "analyticsb@b-BOL.com")

    resp = await client.get("/analytics/summary", headers=headers_a)
    assert resp.json()["total_calls"] == 0
    resp = await client.get("/analytics/summary", headers=headers_b)
    assert resp.json()["total_calls"] == 0


async def test_latency_analytics_empty_org(client):
    headers = await register_and_login(client, "Acme", "latency1@acme-BOL.com")
    resp = await client.get("/analytics/latency", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall"]["call_count"] == 0
    assert body["overall"]["avg_latency_ms"] is None
    assert body["by_transport"] == []
    assert body["by_tts_provider"] == []
    assert body["by_llm_model"] == []


async def test_latency_analytics_groups_by_provider_and_transport(
    client, db_session_factory
):
    headers = await register_and_login(client, "Acme", "latency2@acme-BOL.com")
    resp = await client.post("/agents", json=AGENT_PAYLOAD, headers=headers)
    agent = resp.json()

    async with db_session_factory() as session:
        session.add_all(
            [
                Call(
                    org_id=uuid.UUID(agent["org_id"]),
                    agent_id=uuid.UUID(agent["id"]),
                    direction=CallDirection.outbound,
                    to_number="+15551110000",
                    from_number="+15552220000",
                    status=CallStatus.completed,
                    transport="telephony",
                    tts_provider="fish",
                    llm_model="qwen/qwen3.6-27b",
                    avg_latency_ms=800,
                    p95_latency_ms=1200,
                ),
                Call(
                    org_id=uuid.UUID(agent["org_id"]),
                    agent_id=uuid.UUID(agent["id"]),
                    direction=CallDirection.outbound,
                    to_number="+15551110001",
                    from_number="+15552220000",
                    status=CallStatus.completed,
                    transport="telephony",
                    tts_provider="chatterbox",
                    llm_model="qwen/qwen3.6-27b",
                    avg_latency_ms=1600,
                    p95_latency_ms=2400,
                ),
                Call(
                    org_id=uuid.UUID(agent["org_id"]),
                    agent_id=uuid.UUID(agent["id"]),
                    direction=CallDirection.test,
                    to_number="(browser test)",
                    from_number="tester@acme-BOL.com",
                    status=CallStatus.completed,
                    transport="webrtc",
                    tts_provider="fish",
                    llm_model="qwen/qwen3.6-27b",
                    avg_latency_ms=600,
                    p95_latency_ms=900,
                ),
                # No latency data — must be excluded from every aggregate.
                Call(
                    org_id=uuid.UUID(agent["org_id"]),
                    agent_id=uuid.UUID(agent["id"]),
                    direction=CallDirection.outbound,
                    to_number="+15551110002",
                    from_number="+15552220000",
                    status=CallStatus.failed,
                ),
            ]
        )
        await session.commit()

    resp = await client.get("/analytics/latency", headers=headers)
    assert resp.status_code == 200
    body = resp.json()

    assert body["overall"]["call_count"] == 3
    assert body["overall"]["avg_latency_ms"] == round((800 + 1600 + 600) / 3, 1)

    by_provider = {row["key"]: row for row in body["by_tts_provider"]}
    assert by_provider["fish"]["call_count"] == 2
    assert by_provider["fish"]["avg_latency_ms"] == round((800 + 600) / 2, 1)
    assert by_provider["chatterbox"]["call_count"] == 1
    assert by_provider["chatterbox"]["avg_latency_ms"] == 1600.0

    by_transport = {row["key"]: row for row in body["by_transport"]}
    assert by_transport["telephony"]["call_count"] == 2
    assert by_transport["webrtc"]["call_count"] == 1
