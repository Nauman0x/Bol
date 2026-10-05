"""Covers chunking (pure), document CRUD, and search — embeddings are
always monkeypatched to a deterministic stub (never the real fastembed
model, which needs a one-time network download and is far too slow for a
test suite) so the actual vector math and org-scoping are what's verified.
"""

from app.config import settings
from app.services.knowledge import chunk_text
from tests.conftest import register_and_login

INTERNAL_HEADERS = {"Authorization": f"Bearer {settings.internal_service_token}"}

# 2D stand-in vectors — cosine similarity between these is easy to reason
# about by hand, unlike real 384-dim embeddings.
_VECTORS = {
    "refund": [1.0, 0.0],
    "hours": [0.0, 1.0],
}


async def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
    return [_VECTORS.get(text, [0.5, 0.5]) for text in texts]


def test_chunk_text_splits_long_text_with_overlap():
    text = "a" * 2000
    chunks = chunk_text(text)
    assert len(chunks) > 1
    assert all(chunk for chunk in chunks)


def test_chunk_text_empty_input_returns_no_chunks():
    assert chunk_text("   ") == []
    assert chunk_text("") == []


def test_chunk_text_short_text_is_a_single_chunk():
    assert chunk_text("Refunds are processed within 5 days.") == [
        "Refunds are processed within 5 days."
    ]


async def test_create_list_delete_knowledge_document(client, monkeypatch):
    monkeypatch.setattr("app.routers.knowledge.embed_texts", _fake_embed_texts)
    headers = await register_and_login(client, "Acme", "knowledge1@acme-BOL.com")

    resp = await client.post(
        "/knowledge", json={"name": "Refund policy", "content": "refund"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert doc["name"] == "Refund policy"
    assert doc["chunk_count"] == 1

    resp = await client.get("/knowledge", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = await client.delete(f"/knowledge/{doc['id']}", headers=headers)
    assert resp.status_code == 204

    resp = await client.get("/knowledge", headers=headers)
    assert resp.json() == []


async def test_create_knowledge_document_rejects_empty_content(client, monkeypatch):
    monkeypatch.setattr("app.routers.knowledge.embed_texts", _fake_embed_texts)
    headers = await register_and_login(client, "Acme", "knowledge2@acme-BOL.com")

    resp = await client.post(
        "/knowledge", json={"name": "Empty doc", "content": "   "}, headers=headers
    )
    assert resp.status_code == 400


async def test_delete_unknown_document_404s(client):
    headers = await register_and_login(client, "Acme", "knowledge3@acme-BOL.com")
    resp = await client.delete(
        "/knowledge/00000000-0000-0000-0000-000000000000", headers=headers
    )
    assert resp.status_code == 404


async def test_knowledge_documents_are_org_scoped(client, monkeypatch):
    monkeypatch.setattr("app.routers.knowledge.embed_texts", _fake_embed_texts)
    headers_a = await register_and_login(client, "Acme", "knowledge4@acme-BOL.com")
    headers_b = await register_and_login(client, "Beta", "knowledge5@beta-BOL.com")

    resp = await client.post(
        "/knowledge", json={"name": "Acme doc", "content": "refund"}, headers=headers_a
    )
    doc_id = resp.json()["id"]

    resp = await client.get("/knowledge", headers=headers_b)
    assert resp.json() == []

    resp = await client.delete(f"/knowledge/{doc_id}", headers=headers_b)
    assert resp.status_code == 404


async def test_internal_search_ranks_by_similarity_and_is_org_scoped(client, monkeypatch):
    monkeypatch.setattr("app.services.knowledge.embed_texts", _fake_embed_texts)
    monkeypatch.setattr("app.routers.knowledge.embed_texts", _fake_embed_texts)
    headers = await register_and_login(client, "Acme", "knowledge6@acme-BOL.com")

    resp = await client.post("/agents", headers=headers, json={
        "name": "Agent",
        "config": {"system_prompt": "You are helpful."},
        "tools": [],
    })
    org_id = resp.json()["org_id"]

    await client.post(
        "/knowledge", json={"name": "Refunds", "content": "refund"}, headers=headers
    )
    await client.post(
        "/knowledge", json={"name": "Hours", "content": "hours"}, headers=headers
    )

    resp = await client.post(
        "/internal/knowledge/search",
        json={"org_id": org_id, "query": "refund"},
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 200
    chunks = resp.json()["chunks"]
    assert chunks == ["refund"]


async def test_internal_search_with_no_documents_returns_empty(client):
    resp = await client.post(
        "/internal/knowledge/search",
        json={"org_id": "00000000-0000-0000-0000-000000000000", "query": "anything"},
        headers=INTERNAL_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["chunks"] == []
