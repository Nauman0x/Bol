from tests.conftest import register_and_login


async def test_register_login_me_flow(client):
    resp = await client.post(
        "/auth/register",
        json={
            "org_name": "Acme",
            "name": "Alice",
            "email": "alice@acme-BOL.com",
            "password": "supersecret1",
        },
    )
    assert resp.status_code == 201
    tokens = resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens

    resp = await client.post(
        "/auth/login",
        json={"email": "alice@acme-BOL.com", "password": "supersecret1"},
    )
    assert resp.status_code == 200
    login_tokens = resp.json()

    resp = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {login_tokens['access_token']}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "alice@acme-BOL.com"
    assert body["role"] == "owner"

    resp = await client.post(
        "/auth/refresh", json={"refresh_token": login_tokens["refresh_token"]}
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_password_rejected(client):
    await register_and_login(client, "Acme", "bob@acme-BOL.com")
    resp = await client.post(
        "/auth/login", json={"email": "bob@acme-BOL.com", "password": "wrongpassword"}
    )
    assert resp.status_code == 401


async def test_duplicate_email_registration_rejected(client):
    await register_and_login(client, "Acme", "dup@acme-BOL.com")
    resp = await client.post(
        "/auth/register",
        json={
            "org_name": "Other Org",
            "name": "Dup",
            "email": "dup@acme-BOL.com",
            "password": "supersecret1",
        },
    )
    assert resp.status_code == 409


async def test_unauthenticated_request_rejected(client):
    resp = await client.get("/agents")
    assert resp.status_code == 401
