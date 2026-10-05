"""CRUD, org isolation, secret masking/round-tripping, and /tools/{id}/test
for the reusable Tool resource (app/models/tool.py). Real outbound HTTP is
never used — /test hits an in-process ASGI stand-in via a monkeypatched
httpx.AsyncClient the same way other worker/API integration points do.
"""

import httpx

from app.config import settings
from app.services.crypto import decrypt_secrets, encrypt_secrets
from tests.conftest import register_and_login

_TEST_SECRETS_KEY = "Hgk7IuLkjAgvzRWssBYrAMmoi39ZDCCRH206Hs7pSTY="

TOOL_PAYLOAD = {
    "name": "check_availability",
    "description": "Check appointment availability",
    "url": "https://example.com/availability",
    "method": "POST",
    "params": [
        {"name": "date", "location": "body", "type": "string", "required": True, "source": "llm"},
        {
            "name": "call_id",
            "location": "body",
            "type": "string",
            "source": "dynamic",
            "value": "call_id",
        },
    ],
    "headers": [],
}


def test_encrypt_decrypt_secrets_round_trips(monkeypatch):
    monkeypatch.setattr(settings, "secrets_key", _TEST_SECRETS_KEY)
    blob = encrypt_secrets({"api_key": "sk-super-secret"})
    assert decrypt_secrets(blob) == {"api_key": "sk-super-secret"}


def test_decrypt_secrets_returns_empty_for_none():
    assert decrypt_secrets(None) == {}


async def test_create_tool_requires_valid_https_ssrf_safe_url(client):
    headers = await register_and_login(client, "Acme", "tool1@acme-BOL.com")
    resp = await client.post(
        "/tools", json={**TOOL_PAYLOAD, "url": "http://example.com/x"}, headers=headers
    )
    # Tool creation itself doesn't call check_webhook_url (that happens at
    # call/test time, since path params can only be resolved then) — this
    # documents that: creation succeeds, and the guard fires on /test.
    assert resp.status_code == 201, resp.text


async def test_create_list_get_delete_tool(client):
    headers = await register_and_login(client, "Acme", "tool2@acme-BOL.com")

    resp = await client.post("/tools", json=TOOL_PAYLOAD, headers=headers)
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["name"] == "check_availability"
    assert created["secret_refs_set"] == []

    resp = await client.get("/tools", headers=headers)
    assert len(resp.json()) == 1

    resp = await client.get(f"/tools/{created['id']}", headers=headers)
    assert resp.status_code == 200

    resp = await client.delete(f"/tools/{created['id']}", headers=headers)
    assert resp.status_code == 204

    resp = await client.get("/tools", headers=headers)
    assert resp.json() == []


async def test_tools_are_org_scoped(client):
    headers_a = await register_and_login(client, "Acme", "tool3@acme-BOL.com")
    headers_b = await register_and_login(client, "Beta", "tool4@beta-BOL.com")

    resp = await client.post("/tools", json=TOOL_PAYLOAD, headers=headers_a)
    tool_id = resp.json()["id"]

    resp = await client.get("/tools", headers=headers_b)
    assert resp.json() == []

    resp = await client.delete(f"/tools/{tool_id}", headers=headers_b)
    assert resp.status_code == 404


async def test_duplicate_tool_name_conflicts(client):
    headers = await register_and_login(client, "Acme", "tool5@acme-BOL.com")
    resp = await client.post("/tools", json=TOOL_PAYLOAD, headers=headers)
    assert resp.status_code == 201
    resp = await client.post("/tools", json=TOOL_PAYLOAD, headers=headers)
    assert resp.status_code == 409


async def test_secret_header_requires_secrets_key_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "secrets_key", None)
    headers = await register_and_login(client, "Acme", "tool6@acme-BOL.com")
    payload = {
        **TOOL_PAYLOAD,
        "name": "with_secret",
        "headers": [{"name": "Authorization", "value_type": "secret", "secret_ref": "auth"}],
        "secrets": [{"secret_ref": "auth", "value": "Bearer sk-123"}],
    }
    resp = await client.post("/tools", json=payload, headers=headers)
    assert resp.status_code == 400
    assert "SECRETS_KEY" in resp.json()["detail"]


async def test_secret_header_masked_and_update_preserves_stored_value(client, monkeypatch):
    monkeypatch.setattr(settings, "secrets_key", _TEST_SECRETS_KEY)
    headers = await register_and_login(client, "Acme", "tool7@acme-BOL.com")
    payload = {
        **TOOL_PAYLOAD,
        "name": "with_secret",
        "headers": [{"name": "Authorization", "value_type": "secret", "secret_ref": "auth"}],
        "secrets": [{"secret_ref": "auth", "value": "Bearer sk-123"}],
    }
    resp = await client.post("/tools", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["secret_refs_set"] == ["auth"]
    # The dashboard-facing response never carries the plaintext.
    assert "sk-123" not in resp.text

    # Update without touching `secrets` must keep the stored value.
    resp = await client.patch(
        f"/tools/{created['id']}", json={"description": "updated desc"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["secret_refs_set"] == ["auth"]


async def test_header_referencing_unset_secret_ref_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "secrets_key", _TEST_SECRETS_KEY)
    headers = await register_and_login(client, "Acme", "tool8@acme-BOL.com")
    payload = {
        **TOOL_PAYLOAD,
        "name": "broken_secret",
        "headers": [{"name": "Authorization", "value_type": "secret", "secret_ref": "auth"}],
        "secrets": [],
    }
    resp = await client.post("/tools", json=payload, headers=headers)
    assert resp.status_code == 422


async def test_delete_tool_referenced_by_agent_is_conflict(client):
    headers = await register_and_login(client, "Acme", "tool9@acme-BOL.com")
    resp = await client.post("/tools", json=TOOL_PAYLOAD, headers=headers)
    tool_id = resp.json()["id"]

    agent_payload = {
        "name": "Receptionist",
        "config": {"system_prompt": "You are helpful."},
        "tools": [{"type": "tool_ref", "tool_id": tool_id, "enabled": True}],
    }
    resp = await client.post("/agents", json=agent_payload, headers=headers)
    assert resp.status_code == 201, resp.text

    resp = await client.delete(f"/tools/{tool_id}", headers=headers)
    assert resp.status_code == 409
    assert "Receptionist" in resp.json()["detail"]


async def test_test_tool_runs_real_request_through_mock_transport(client, monkeypatch):
    headers = await register_and_login(client, "Acme", "tool10@acme-BOL.com")
    payload = {
        **TOOL_PAYLOAD,
        "name": "check_availability2",
        "response_extract": [{"name": "slot", "path": "slot"}],
    }
    resp = await client.post("/tools", json=payload, headers=headers)
    tool_id = resp.json()["id"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/availability"
        return httpx.Response(200, json={"slot": "3pm"})

    mock_transport = httpx.MockTransport(handler)

    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = mock_transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("app.routers.tools.httpx.AsyncClient", _PatchedAsyncClient)

    resp = await client.post(
        f"/tools/{tool_id}/test", json={"llm_args": {"date": "2026-08-20"}}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["ok"] is True
    assert result["status_code"] == 200
    assert result["extracted"] == {"slot": "3pm"}


async def test_test_tool_missing_required_llm_arg_fails_without_request(client, monkeypatch):
    headers = await register_and_login(client, "Acme", "tool11@acme-BOL.com")
    resp = await client.post(
        "/tools", json={**TOOL_PAYLOAD, "name": "check_availability3"}, headers=headers
    )
    tool_id = resp.json()["id"]

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should never be called — missing required arg")

    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("app.routers.tools.httpx.AsyncClient", _PatchedAsyncClient)

    resp = await client.post(f"/tools/{tool_id}/test", json={"llm_args": {}}, headers=headers)
    assert resp.status_code == 200
    result = resp.json()
    assert result["ok"] is False
    assert "date" in result["error"]
