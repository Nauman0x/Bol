"""Registry of TTS providers the platform can route agents to.

Adding a provider is three small edits: an entry here, a matching branch in
worker/pipeline.py's build_tts, and (if it needs live voice discovery) a
fetcher in app/routers/voices.py.
"""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter

from app.config import settings
from app.security import CurrentUser


@dataclass(frozen=True)
class TtsProviderInfo:
    id: str
    label: str
    streaming: bool
    configured: Callable[[], bool]


TTS_PROVIDERS: dict[str, TtsProviderInfo] = {
    "groq": TtsProviderInfo(
        id="groq",
        label="Groq (Orpheus)",
        streaming=False,
        configured=lambda: bool(settings.groq_api_key),
    ),
    "fish": TtsProviderInfo(
        id="fish",
        label="Fish Audio",
        streaming=True,
        configured=lambda: bool(settings.fish_api_key),
    ),
    "chatterbox": TtsProviderInfo(
        id="chatterbox",
        label="Chatterbox (self-hosted)",
        streaming=False,
        configured=lambda: bool(settings.chatterbox_base_url),
    ),
}


def resolve_tts_provider(config: dict) -> str:
    """The provider id an agent's build_tts (worker/pipeline.py) will
    actually use. Shared so the API can tag a Call row with the right
    provider at creation time — before the worker ever picks up the job,
    and without waiting on it to report back — using the exact same
    resolution logic instead of a second copy that could drift."""
    return config.get("tts_provider") or settings.tts_provider


def resolve_llm_model(config: dict) -> str:
    """Same idea as resolve_tts_provider, for the LLM model id."""
    return config.get("llm_model") or settings.llm_model


router = APIRouter(tags=["tts-providers"])


@router.get("/tts-providers")
async def list_tts_providers(current_user: CurrentUser) -> list[dict]:
    return [
        {
            "id": p.id,
            "label": p.label,
            "streaming": p.streaming,
            "configured": p.configured(),
        }
        for p in TTS_PROVIDERS.values()
    ]
