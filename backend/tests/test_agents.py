import pytest

AGENT_CONFIG = {
    "system_prompt": "You are a helpful assistant.",
    "greeting": "Hi there!",
    "language": "en",
    "voice_id": "arista",
    "llm_model": "qwen/qwen3-32b",
    "temperature": 0.7,
    "max_call_duration_sec": 300,
}


async def _register_and_login(client, email: str) -> str:
    resp = await client.post(
        "/auth/register",
        json={"org_name": "Org", "email": email, "password": "supersecret123", "name": "User"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_agent_crud_flow(client):
    token = await _register_and_login(client, "crud@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = await client.post(
        "/agents", json={"name": "Support Bot", "config": AGENT_CONFIG}, headers=headers
    )
    assert create_resp.status_code == 201
    agent = create_resp.json()
    agent_id = agent["id"]

    list_resp = await client.get("/agents", headers=headers)
    assert len(list_resp.json()) == 1

    get_resp = await client.get(f"/agents/{agent_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Support Bot"

    patch_resp = await client.patch(f"/agents/{agent_id}", json={"name": "Renamed"}, headers=headers)
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "Renamed"

    delete_resp = await client.delete(f"/agents/{agent_id}", headers=headers)
    assert delete_resp.status_code == 204

    final_get = await client.get(f"/agents/{agent_id}", headers=headers)
    assert final_get.status_code == 404


@pytest.mark.asyncio
async def test_cross_org_agent_access_blocked(client):
    token_a = await _register_and_login(client, "orga@test.com")
    token_b = await _register_and_login(client, "orgb@test.com")

    create_resp = await client.post(
        "/agents",
        json={"name": "Org A Agent", "config": AGENT_CONFIG},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    agent_id = create_resp.json()["id"]

    cross_get = await client.get(
        f"/agents/{agent_id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert cross_get.status_code == 404

    cross_list = await client.get("/agents", headers={"Authorization": f"Bearer {token_b}"})
    assert cross_list.json() == []


@pytest.mark.asyncio
async def test_voices_catalog(client):
    resp = await client.get("/voices")
    assert resp.status_code == 200
    assert len(resp.json()) > 0
