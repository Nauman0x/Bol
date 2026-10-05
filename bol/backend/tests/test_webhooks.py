from tests.conftest import register_and_login


async def test_create_webhook_requires_https(client):
    headers = await register_and_login(client, "Acme", "webhook1@acme-BOL.com")
    resp = await client.post(
        "/webhooks", json={"url": "http://example.com/hook"}, headers=headers
    )
    assert resp.status_code == 422


async def test_create_webhook_rejects_private_address(client):
    headers = await register_and_login(client, "Acme", "webhook2@acme-BOL.com")
    resp = await client.post(
        "/webhooks", json={"url": "https://localhost/hook"}, headers=headers
    )
    assert resp.status_code == 422


async def test_create_list_delete_webhook(client):
    headers = await register_and_login(client, "Acme", "webhook3@acme-BOL.com")

    resp = await client.post(
        "/webhooks",
        json={"url": "https://example.com/hook", "events": ["call.completed"]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["url"] == "https://example.com/hook"
    assert "secret" in created and created["secret"]

    resp = await client.get("/webhooks", headers=headers)
    assert resp.status_code == 200
    listed = resp.json()
    assert len(listed) == 1
    # secret is returned once at creation only, never in list responses.
    assert "secret" not in listed[0]

    resp = await client.delete(f"/webhooks/{created['id']}", headers=headers)
    assert resp.status_code == 204

    resp = await client.get("/webhooks", headers=headers)
    assert resp.json() == []


async def test_delete_unknown_webhook_404s(client):
    headers = await register_and_login(client, "Acme", "webhook4@acme-BOL.com")
    resp = await client.delete(
        "/webhooks/00000000-0000-0000-0000-000000000000", headers=headers
    )
    assert resp.status_code == 404


async def test_webhooks_are_org_scoped(client):
    headers_a = await register_and_login(client, "Acme", "webhook5@acme-BOL.com")
    headers_b = await register_and_login(client, "Beta", "webhook6@beta-BOL.com")

    resp = await client.post(
        "/webhooks", json={"url": "https://example.com/hook"}, headers=headers_a
    )
    webhook_id = resp.json()["id"]

    resp = await client.get("/webhooks", headers=headers_b)
    assert resp.json() == []

    resp = await client.delete(f"/webhooks/{webhook_id}", headers=headers_b)
    assert resp.status_code == 404
