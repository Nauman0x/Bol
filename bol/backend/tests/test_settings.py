from tests.conftest import register_and_login

# --- Team ---


async def test_list_team_shows_only_own_org_members(client):
    headers_a = await register_and_login(client, "Org A", "teama@a-BOL.com")
    await register_and_login(client, "Org B", "teamb@b-BOL.com")

    resp = await client.get("/team", headers=headers_a)
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    assert emails == ["teama@a-BOL.com"]


async def test_invite_creates_member_with_temp_password(client):
    headers = await register_and_login(client, "Acme", "inviter@acme-BOL.com")

    resp = await client.post(
        "/team/invite",
        json={"email": "newbie@acme-BOL.com", "name": "Newbie", "role": "member"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "newbie@acme-BOL.com"
    assert body["role"] == "member"
    assert len(body["temp_password"]) > 8

    # The temp password actually works
    resp = await client.post(
        "/auth/login",
        json={"email": "newbie@acme-BOL.com", "password": body["temp_password"]},
    )
    assert resp.status_code == 200

    resp = await client.get("/team", headers=headers)
    assert len(resp.json()) == 2


async def test_invited_member_lands_in_inviters_org(client):
    headers = await register_and_login(client, "Acme", "owner2@acme-BOL.com")
    resp = await client.post(
        "/team/invite",
        json={"email": "colleague@acme-BOL.com", "name": "Colleague", "role": "member"},
        headers=headers,
    )
    temp_password = resp.json()["temp_password"]

    resp = await client.post(
        "/auth/login", json={"email": "colleague@acme-BOL.com", "password": temp_password}
    )
    member_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = await client.get("/auth/me", headers=member_headers)
    member_org = resp.json()["org_id"]
    resp = await client.get("/auth/me", headers=headers)
    assert member_org == resp.json()["org_id"]


async def test_invite_duplicate_email_rejected(client):
    headers = await register_and_login(client, "Acme", "dupinviter@acme-BOL.com")
    resp = await client.post(
        "/team/invite",
        json={"email": "dupinviter@acme-BOL.com", "name": "Dup", "role": "member"},
        headers=headers,
    )
    assert resp.status_code == 409


async def test_member_cannot_invite(client):
    headers = await register_and_login(client, "Acme", "boss@acme-BOL.com")
    resp = await client.post(
        "/team/invite",
        json={"email": "grunt@acme-BOL.com", "name": "Grunt", "role": "member"},
        headers=headers,
    )
    temp_password = resp.json()["temp_password"]
    resp = await client.post(
        "/auth/login", json={"email": "grunt@acme-BOL.com", "password": temp_password}
    )
    member_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = await client.post(
        "/team/invite",
        json={"email": "another@acme-BOL.com", "name": "Another", "role": "member"},
        headers=member_headers,
    )
    assert resp.status_code == 403


# --- Organization ---


async def test_get_and_rename_organization(client):
    headers = await register_and_login(client, "Old Name", "orgowner@acme-BOL.com")

    resp = await client.get("/organization", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Old Name"

    resp = await client.patch("/organization", json={"name": "New Name"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"

    resp = await client.get("/organization", headers=headers)
    assert resp.json()["name"] == "New Name"


async def test_rename_organization_does_not_affect_other_orgs(client):
    headers_a = await register_and_login(client, "Org A", "renamea@a-BOL.com")
    headers_b = await register_and_login(client, "Org B", "renameb@b-BOL.com")

    await client.patch("/organization", json={"name": "Renamed A"}, headers=headers_a)

    resp = await client.get("/organization", headers=headers_b)
    assert resp.json()["name"] == "Org B"


# --- API keys ---


async def test_api_key_create_reveals_once_then_lists_without_secret(client):
    headers = await register_and_login(client, "Acme", "keys@acme-BOL.com")

    resp = await client.post("/api_keys", json={"name": "CI key"}, headers=headers)
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["key"].startswith("BOL_sk_")
    assert created["prefix"] == created["key"][: len(created["prefix"])]

    resp = await client.get("/api_keys", headers=headers)
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) == 1
    # The plaintext key is never returned again
    assert "key" not in keys[0]
    assert keys[0]["prefix"] == created["prefix"]


async def test_api_key_revoke(client):
    headers = await register_and_login(client, "Acme", "revoke@acme-BOL.com")
    resp = await client.post("/api_keys", json={"name": "Temp key"}, headers=headers)
    key_id = resp.json()["id"]

    resp = await client.delete(f"/api_keys/{key_id}", headers=headers)
    assert resp.status_code == 204

    resp = await client.get("/api_keys", headers=headers)
    assert resp.json() == []


async def test_api_key_actually_authenticates_requests(client):
    headers = await register_and_login(client, "Acme", "apikeyauth@acme-BOL.com")
    resp = await client.post("/api_keys", json={"name": "CI key"}, headers=headers)
    raw_key = resp.json()["key"]

    resp = await client.get("/api_keys", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200


async def test_api_key_last_used_at_is_throttled(client, db_session_factory):
    import uuid

    from app.models.api_key import ApiKey

    headers = await register_and_login(client, "Acme", "apikeythrottle@acme-BOL.com")
    resp = await client.post("/api_keys", json={"name": "CI key"}, headers=headers)
    key_id = uuid.UUID(resp.json()["id"])
    raw_key = resp.json()["key"]
    key_headers = {"Authorization": f"Bearer {raw_key}"}

    await client.get("/api_keys", headers=key_headers)
    async with db_session_factory() as session:
        key = await session.get(ApiKey, key_id)
        first_seen = key.last_used_at
    assert first_seen is not None

    # A second use immediately after must not re-write the timestamp — the
    # throttle window (60s) hasn't elapsed.
    await client.get("/api_keys", headers=key_headers)
    async with db_session_factory() as session:
        key = await session.get(ApiKey, key_id)
        assert key.last_used_at == first_seen


async def test_cross_org_api_key_access_is_blocked(client):
    headers_a = await register_and_login(client, "Org A", "keysa@a-BOL.com")
    headers_b = await register_and_login(client, "Org B", "keysb@b-BOL.com")

    resp = await client.post("/api_keys", json={"name": "A's key"}, headers=headers_a)
    key_id = resp.json()["id"]

    resp = await client.get("/api_keys", headers=headers_b)
    assert resp.json() == []

    resp = await client.delete(f"/api_keys/{key_id}", headers=headers_b)
    assert resp.status_code == 404

    # A's key survives B's attempt
    resp = await client.get("/api_keys", headers=headers_a)
    assert len(resp.json()) == 1


async def test_settings_endpoints_require_auth(client):
    for method, path in [
        ("GET", "/team"),
        ("GET", "/organization"),
        ("GET", "/api_keys"),
    ]:
        resp = await client.request(method, path)
        assert resp.status_code == 401, f"{method} {path} should require auth"
