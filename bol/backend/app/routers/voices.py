"""Voice catalog, fetched live per provider where possible.

Groq's voices are a fixed, small set (no discovery API), so they stay
hardcoded. Fish Audio and Chatterbox voices are fetched from their APIs and
cached in Redis — an operator can add a Fish voice or upload a Chatterbox
voice without a BOL deploy. When aggregating across all providers (no
`provider` query param), every fetcher degrades to an empty list (logged, not
raised) on failure, so a misconfigured or unreachable provider never breaks
the rest of the agent-builder form. A request for one specific provider
raises instead, surfaced as a 502 — see list_voices — so "unreachable" isn't
silently indistinguishable from "genuinely has zero voices".
"""

import asyncio
import logging
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.cache import cache_get_json, cache_set_json
from app.config import settings
from app.security import CurrentUser

logger = logging.getLogger("BOL.api")

router = APIRouter(prefix="/voices", tags=["voices"])

_CACHE_TTL_SEC = 600
# Chatterbox's non-streaming synthesis path blocks its own event loop
# (see deploy/chatterbox/vendor/server.py), so /audio/voices can go
# unserved for the duration of an in-flight synthesis (~15-25s observed on
# CPU) — 3s was tripping on a live server, not just a dead one.
_FETCH_TIMEOUT_SEC = 20.0

TtsProviderId = Literal["groq", "fish", "chatterbox"]


def _normalize_lang(code: str) -> str:
    """BCP-47-ish tags ("es-ES", "en_US") down to their primary subtag
    ("es", "en") — Fish's API returns the former, BOL's agent config
    stores the latter (app/schemas/agent.py), so leaving them unnormalized
    meant a Spanish agent's voice picker silently matched nothing against a
    Fish voice tagged "es-ES"."""
    return code.strip().lower().replace("_", "-").split("-")[0]


class Voice(BaseModel):
    id: str
    label: str
    # Kept for older/simpler callers — always languages[0]. The
    # agent-builder's voice picker matches against the full `languages`
    # list below, not this field, since some Fish voices speak several.
    language: str
    languages: list[str]
    provider: str


# The full, real set of voices the livekit-plugins-groq TTS plugin accepts
# (TTSVoices Literal in the installed plugin's models.py) — "default" /
# "ar-default" were never valid voice ids; build_tts's _LEGACY_GROQ_VOICE_ALIASES
# maps those two stored-config values onto autumn/noura so agents saved before
# this fix keep working.
_GROQ_VOICES: list[Voice] = [
    Voice(id="autumn", label="Autumn (English)", language="en", languages=["en"], provider="groq"),
    Voice(id="diana", label="Diana (English)", language="en", languages=["en"], provider="groq"),
    Voice(id="hannah", label="Hannah (English)", language="en", languages=["en"], provider="groq"),
    Voice(id="austin", label="Austin (English)", language="en", languages=["en"], provider="groq"),
    Voice(id="daniel", label="Daniel (English)", language="en", languages=["en"], provider="groq"),
    Voice(id="troy", label="Troy (English)", language="en", languages=["en"], provider="groq"),
    Voice(id="fahad", label="Fahad (Arabic)", language="ar", languages=["ar"], provider="groq"),
    Voice(id="sultan", label="Sultan (Arabic)", language="ar", languages=["ar"], provider="groq"),
    Voice(id="lulwa", label="Lulwa (Arabic)", language="ar", languages=["ar"], provider="groq"),
    Voice(id="noura", label="Noura (Arabic)", language="ar", languages=["ar"], provider="groq"),
]

# livekit-plugins-fishaudio's own TTS(voice_id=...) default — a real,
# vendor-guaranteed voice id (not a guess), used only as a fallback so a
# transient Fish API outage doesn't leave the dropdown empty when the key
# IS configured. Source: livekit.plugins.fishaudio.tts.DEFAULT_VOICE_ID.
_FISH_FALLBACK_VOICE = Voice(
    id="933563129e564b19a115bedd57b7406a",
    label="Fish Default",
    language="en",
    languages=["en"],
    provider="fish",
)


async def _fetch_fish_voices() -> list[Voice]:
    if not settings.fish_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SEC) as client:
            resp = await client.get(
                "https://api.fish.audio/model",
                params={"page_size": 100, "self": "true"},
                headers={"Authorization": f"Bearer {settings.fish_api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("Failed to fetch Fish Audio voice list")
        raise

    voices: list[Voice] = []
    for item in data.get("items", []):
        reference_id = item.get("_id")
        if not reference_id:
            continue
        raw_languages = item.get("languages") or ["en"]
        normalized_languages = [_normalize_lang(lang) for lang in raw_languages] or ["en"]
        voices.append(
            Voice(
                id=reference_id,
                label=item.get("title") or reference_id,
                language=normalized_languages[0],
                languages=normalized_languages,
                provider="fish",
            )
        )
    return voices


async def _fetch_chatterbox_voices() -> list[Voice]:
    if not settings.chatterbox_base_url:
        return []
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SEC) as client:
            resp = await client.get(f"{settings.chatterbox_base_url}/audio/voices")
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("Failed to fetch Chatterbox voice list")
        raise

    # devnen/Chatterbox-TTS-Server's OpenAI-compatible endpoint returns
    # either {"voices": [...]}, or a bare list — the entries are either
    # plain name strings or {"id"/"name": ...} objects depending on server
    # version, so both shapes are handled defensively.
    raw_voices = data.get("voices", data) if isinstance(data, dict) else data
    voices: list[Voice] = []
    for item in raw_voices or []:
        if isinstance(item, dict):
            voice_id = item.get("id") or item.get("name")
            label = item.get("name") or voice_id
        else:
            voice_id = label = item
        if not voice_id:
            continue
        # No per-voice language metadata from this server — the frontend
        # special-cases provider=="chatterbox" to skip language filtering
        # entirely rather than trust this placeholder (agent-form.tsx).
        voices.append(
            Voice(id=voice_id, label=label, language="en", languages=["en"], provider="chatterbox")
        )
    return voices


_LIVE_FETCHERS = {
    "fish": _fetch_fish_voices,
    "chatterbox": _fetch_chatterbox_voices,
}


async def _get_voices(provider: TtsProviderId, *, raise_on_error: bool = False) -> list[Voice]:
    if provider == "groq":
        return _GROQ_VOICES

    cache_key = f"voices:{provider}"
    cached = await cache_get_json(cache_key)
    if cached is not None:
        return [Voice(**v) for v in cached]

    try:
        voices = await _LIVE_FETCHERS[provider]()
    except Exception:
        if raise_on_error:
            # A caller asking about this one provider specifically (e.g. the
            # voice picker for an agent already using it) wants to know the
            # difference between "unreachable" and "genuinely zero voices" —
            # swallowing this into [] made a Chatterbox ReadTimeout
            # indistinguishable from an empty catalog (see list_voices).
            raise
        # Aggregate/background callers get the old graceful degrade: Fish
        # gets a hardcoded fallback voice so the dropdown isn't fully empty
        # (Chatterbox has no such default), but crucially neither result is
        # cached: caching a degraded result here would leave the dropdown
        # wrong for the full 10-minute TTL even after the provider recovers.
        return [_FISH_FALLBACK_VOICE] if provider == "fish" else []

    if voices:
        await cache_set_json(cache_key, [v.model_dump() for v in voices], _CACHE_TTL_SEC)
    return voices


@router.get("", response_model=list[Voice])
async def list_voices(
    current_user: CurrentUser,
    # Inlined rather than the TtsProviderId alias: ruff's B008 check
    # (function call in a default) doesn't recognize Query() as immutable
    # when the annotation is a Literal type alias, only a literal Literal[...].
    provider: Literal["groq", "fish", "chatterbox"] | None = Query(default=None),
) -> list[Voice]:
    if provider is not None:
        # Fish already has a graceful degrade worth keeping for a direct
        # query too (a hardcoded fallback voice, see _get_voices) — only
        # Chatterbox has no such fallback, which is what made "unreachable"
        # and "genuinely zero voices" indistinguishable (both -> 200 []).
        if provider != "chatterbox":
            return await _get_voices(provider)
        try:
            return await _get_voices(provider, raise_on_error=True)
        except Exception as exc:
            # 502 (not a silent 200 []) so the frontend can tell "Chatterbox
            # is unreachable" apart from "Chatterbox has no voices
            # configured" instead of treating both the same way.
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not fetch voices from {provider}",
            ) from exc

    # No provider given: aggregate across all three so existing callers
    # (and a fresh agent-builder form before a provider is chosen) still
    # get a full list, degrading gracefully per-provider rather than failing
    # the whole request for one unreachable provider.
    results = await asyncio.gather(*(_get_voices(p) for p in ("groq", "fish", "chatterbox")))
    return [voice for group in results for voice in group]
