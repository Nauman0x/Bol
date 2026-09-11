import pytest


@pytest.mark.asyncio
async def test_register_login_me_flow(client):
    register_resp = await client.post(
        "/auth/register",
        json={
            "org_name": "Acme Inc",
            "email": "Owner@Acme.com",
            "password": "supersecret123",
            "name": "Owner",
        },
    )
    assert register_resp.status_code == 201
    tokens = register_resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens

    login_resp = await client.post(
        "/auth/login", json={"email": "owner@acme.com", "password": "supersecret123"}
    )
    assert login_resp.status_code == 200
    login_tokens = login_resp.json()

    me_resp = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {login_tokens['access_token']}"}
    )
    assert me_resp.status_code == 200
    body = me_resp.json()
    assert body["email"] == "owner@acme.com"
    assert body["role"] == "owner"


@pytest.mark.asyncio
async def test_login_wrong_password_rejected(client):
    await client.post(
        "/auth/register",
        json={"org_name": "Acme", "email": "a@b.com", "password": "supersecret123", "name": "A"},
    )
    resp = await client.post("/auth/login", json={"email": "a@b.com", "password": "wrongpass"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_duplicate_email_rejected(client):
    payload = {"org_name": "Acme", "email": "dup@b.com", "password": "supersecret123", "name": "A"}
    first = await client.post("/auth/register", json=payload)
    assert first.status_code == 201
    second = await client.post("/auth/register", json=payload)
    assert second.status_code == 409
