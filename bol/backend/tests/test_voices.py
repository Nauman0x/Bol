import httpx

from app.config import settings
from app.routers.voices import _normalize_lang
from tests.conftest import register_and_login


def test_normalize_lang_strips_region_subtag():
    assert _normalize_lang("es-ES") == "es"
    assert _normalize_lang("en_US") == "en"
    assert _normalize_lang("PT-br") == "pt"
    assert _normalize_lang("ja") == "ja"


class _FishVoicesHttpxClient:
    """Returns a fixed Fish /model response with a region-tagged language,
    like the real API does — see app.routers.voices._fetch_fish_voices."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        return httpx.Response(
            200,
            json={
                "items": [
                    {"_id": "voice-1", "title": "Spanish Voice", "languages": ["es-ES"]},
                    {"_id": "voice-2", "title": "Multi Voice", "languages": ["en-US", "fr-FR"]},
                ]
            },
            request=httpx.Request("GET", "https://api.fish.audio/model"),
        )


class _UnreachableHttpxClient:
    """Stand-in for httpx.AsyncClient — every request raises, like a
    downed Fish API or an unreachable Chatterbox box. Patched onto
    app.routers.voices.httpx.AsyncClient specifically (not the class
    globally) so the test client's own httpx usage is unaffected."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        raise httpx.ConnectError("boom")


async def test_voices_groq_only_when_others_unconfigured(client, monkeypatch):
    monkeypatch.setattr(settings, "fish_api_key", "")
    monkeypatch.setattr(settings, "chatterbox_base_url", "")
    headers = await register_and_login(client, "Acme", "voices1@acme-BOL.com")

    resp = await client.get("/voices", headers=headers)
    assert resp.status_code == 200
    providers = {v["provider"] for v in resp.json()}
    assert providers == {"groq"}


async def test_voices_fish_falls_back_to_seed_on_api_failure(client, monkeypatch):
    monkeypatch.setattr(settings, "fish_api_key", "fish_test_key")
    monkeypatch.setattr(
        "app.routers.voices.httpx.AsyncClient", lambda **kwargs: _UnreachableHttpxClient()
    )

    headers = await register_and_login(client, "Acme", "voices2@acme-BOL.com")
    resp = await client.get("/voices", headers=headers, params={"provider": "fish"})
    assert resp.status_code == 200
    voices = resp.json()
    # Must never come back empty/erroring just because the Fish API is down —
    # falls back to the plugin's own known-good default voice.
    assert len(voices) == 1
    assert voices[0]["provider"] == "fish"


async def test_voices_fish_languages_are_normalized(client, monkeypatch):
    monkeypatch.setattr(settings, "fish_api_key", "fish_test_key")
    monkeypatch.setattr(
        "app.routers.voices.httpx.AsyncClient", lambda **kwargs: _FishVoicesHttpxClient()
    )

    headers = await register_and_login(client, "Acme", "voices4@acme-BOL.com")
    resp = await client.get("/voices", headers=headers, params={"provider": "fish"})
    assert resp.status_code == 200
    by_id = {v["id"]: v for v in resp.json()}
    assert by_id["voice-1"]["language"] == "es"
    assert by_id["voice-1"]["languages"] == ["es"]
    assert by_id["voice-2"]["languages"] == ["en", "fr"]


async def test_voices_chatterbox_502s_on_direct_query_when_unreachable(client, monkeypatch):
    monkeypatch.setattr(settings, "chatterbox_base_url", "http://unreachable-gpu-host:8004/v1")
    monkeypatch.setattr(
        "app.routers.voices.httpx.AsyncClient", lambda **kwargs: _UnreachableHttpxClient()
    )

    headers = await register_and_login(client, "Acme", "voices3@acme-BOL.com")
    # A direct ?provider=chatterbox query must surface "unreachable" as an
    # error, not a silent 200 [] — Chatterbox has no fallback voice like Fish
    # does, so an empty list here would be indistinguishable from "this
    # server genuinely has zero voices configured".
    resp = await client.get("/voices", headers=headers, params={"provider": "chatterbox"})
    assert resp.status_code == 502


async def test_voices_chatterbox_empty_in_aggregate_when_server_unreachable(client, monkeypatch):
    monkeypatch.setattr(settings, "chatterbox_base_url", "http://unreachable-gpu-host:8004/v1")
    monkeypatch.setattr(
        "app.routers.voices.httpx.AsyncClient", lambda **kwargs: _UnreachableHttpxClient()
    )

    headers = await register_and_login(client, "Acme", "voices3b@acme-BOL.com")
    # The no-provider aggregate call (fresh agent-builder form before a
    # provider is chosen) still degrades gracefully per-provider rather than
    # failing the whole request for one unreachable provider.
    resp = await client.get("/voices", headers=headers)
    assert resp.status_code == 200
    providers = {v["provider"] for v in resp.json()}
    assert "chatterbox" not in providers


async def test_tts_providers_reports_configured_state(client, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gk_test")
    monkeypatch.setattr(settings, "fish_api_key", "")
    monkeypatch.setattr(settings, "chatterbox_base_url", "")

    headers = await register_and_login(client, "Acme", "ttsproviders@acme-BOL.com")
    resp = await client.get("/tts-providers", headers=headers)
    assert resp.status_code == 200
    by_id = {p["id"]: p for p in resp.json()}
    assert by_id["groq"]["configured"] is True
    assert by_id["fish"]["configured"] is False
    assert by_id["chatterbox"]["configured"] is False
    assert by_id["fish"]["streaming"] is True
    assert by_id["groq"]["streaming"] is False
