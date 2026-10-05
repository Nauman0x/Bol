from typing import get_args

from app.config import settings
from app.interruption import INTERRUPTION_PRESETS, adaptive_supported, resolve_interruption
from app.schemas.agent import AgentConfig
from tests.conftest import register_and_login


def test_preset_table_matches_schema_literal():
    # Drift guard: every non-"custom" value the schema's interruption_style
    # Literal accepts must have a preset, and vice versa — a mismatch means
    # either a preset with no way to select it, or a style that silently
    # falls back to "balanced" instead of doing what its name promises.
    schema_styles = set(get_args(AgentConfig.model_fields["interruption_style"].annotation))
    assert schema_styles - {"custom"} == set(INTERRUPTION_PRESETS)


def test_resolve_interruption_unknown_style_never_raises():
    assert resolve_interruption({"interruption_style": "not-a-real-style"}) == resolve_interruption(
        {"interruption_style": "balanced"}
    )


def test_adaptive_supported_reflects_stt_provider(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "livekit")
    assert adaptive_supported() is True
    monkeypatch.setattr(settings, "stt_provider", "groq")
    assert adaptive_supported() is False


async def test_interruption_presets_endpoint_requires_auth(client):
    resp = await client.get("/interruption-presets")
    assert resp.status_code == 401


async def test_interruption_presets_endpoint_reflects_stt_provider(client, monkeypatch):
    headers = await register_and_login(client, "Acme", "presets1@acme-BOL.com")

    monkeypatch.setattr(settings, "stt_provider", "livekit")
    resp = await client.get("/interruption-presets", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["adaptive_supported"] is True
    assert body["adaptive_unsupported_reason"] is None
    assert {p["id"] for p in body["presets"]} == set(INTERRUPTION_PRESETS)

    monkeypatch.setattr(settings, "stt_provider", "groq")
    resp = await client.get("/interruption-presets", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["adaptive_supported"] is False
    assert body["adaptive_unsupported_reason"]
