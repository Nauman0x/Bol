from tests.conftest import register_and_login


async def test_number_crud_flow(client):
    headers = await register_and_login(client, "Acme", "numbers@acme-BOL.com")

    resp = await client.post("/phone_numbers", json={"e164": "+15551234567"}, headers=headers)
    assert resp.status_code == 201, resp.text
    number_id = resp.json()["id"]

    resp = await client.get("/phone_numbers", headers=headers)
    assert len(resp.json()) == 1

    resp = await client.post("/phone_numbers", json={"e164": "+15551234567"}, headers=headers)
    assert resp.status_code == 409

    resp = await client.patch(
        f"/phone_numbers/{number_id}",
        json={"livekit_trunk_id": "trunk_abc123"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["livekit_trunk_id"] == "trunk_abc123"

    resp = await client.delete(f"/phone_numbers/{number_id}", headers=headers)
    assert resp.status_code == 204


async def test_number_rejects_invalid_e164(client):
    headers = await register_and_login(client, "Acme", "badnum@acme-BOL.com")
    resp = await client.post("/phone_numbers", json={"e164": "not-a-number"}, headers=headers)
    assert resp.status_code == 422


async def test_number_rejects_unknown_inbound_agent(client):
    headers = await register_and_login(client, "Acme", "unknownagent@acme-BOL.com")
    resp = await client.post(
        "/phone_numbers",
        json={"e164": "+15559999999", "inbound_agent_id": "00000000-0000-0000-0000-000000000000"},
        headers=headers,
    )
    assert resp.status_code == 400


async def test_voices_catalog_requires_auth_and_returns_entries(client):
    resp = await client.get("/voices")
    assert resp.status_code == 401

    headers = await register_and_login(client, "Acme", "voices@acme-BOL.com")
    resp = await client.get("/voices", headers=headers)
    assert resp.status_code == 200
    ids = [v["id"] for v in resp.json()]
    assert "autumn" in ids
