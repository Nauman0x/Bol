"""Registry of barge-in ("interruption") presets an agent can pick.

Single source of truth for how a per-agent `interruption_style` (plus, for
"custom", the explicit override fields) expands into the concrete values
worker/pipeline.py's build_turn_handling passes to AgentSession. Both the API
(for validation/echo) and the frontend (via GET /interruption-presets, so the
picker never hardcodes a second copy) go through resolve_interruption/
adaptive_supported instead of re-deriving these numbers — mirrors
app/tts_providers.py's registry-dataclass-plus-resolver shape.
"""

from dataclasses import dataclass

from fastapi import APIRouter

from app.config import settings
from app.security import CurrentUser


@dataclass(frozen=True)
class InterruptionPreset:
    id: str
    label: str
    description: str
    min_duration: float
    min_words: int
    false_interruption_timeout: float


# "balanced" is deliberately identical to the values this codebase has run
# with before per-agent interruption settings existed (worker/agent.py's old
# hardcoded turn_handling: min_duration=0.3, plus the framework default
# false_interruption_timeout=2.0, min_words=0 — see voice/turn.py's
# _INTERRUPTION_DEFAULTS in the installed livekit-agents). Every agent saved
# before this feature has none of the new config keys and must resolve here
# to those exact numbers — see test_pipeline.py's regression-lock test.
INTERRUPTION_PRESETS: dict[str, InterruptionPreset] = {
    "instant": InterruptionPreset(
        id="instant",
        label="Instant",
        description="Stops the moment the caller makes a sound. Most responsive, most false interruptions.",
        min_duration=0.15,
        min_words=0,
        false_interruption_timeout=1.0,
    ),
    "balanced": InterruptionPreset(
        id="balanced",
        label="Balanced",
        description="Ignores brief sounds like \"mhm\" or a cough. Recommended default.",
        min_duration=0.3,
        min_words=0,
        false_interruption_timeout=2.0,
    ),
    "patient": InterruptionPreset(
        id="patient",
        label="Patient",
        description=(
            "Only stops for a clear, sustained interruption. min_words only takes "
            "effect with a streaming STT provider (STT_PROVIDER=livekit) — with the "
            "Groq STT fallback, which has no interim transcripts, it has no effect."
        ),
        min_duration=0.6,
        min_words=2,
        false_interruption_timeout=2.5,
    ),
}


def adaptive_supported() -> bool:
    """Adaptive (ML) interruption detection needs a streaming STT with
    word-level timestamps to gatekeep transcripts — only the "livekit"
    STT_PROVIDER path (Deepgram Flux / AssemblyAI via LiveKit inference)
    qualifies; the Groq STT fallback is non-streaming. See
    worker/pipeline.py:build_stt and build_turn_handling."""
    return settings.stt_provider == "livekit"


def resolve_interruption(config: dict) -> dict:
    """The concrete {min_duration, min_words, false_interruption_timeout}
    an agent's build_turn_handling (worker/pipeline.py) will actually use.
    Shared so the API can echo/validate the resolved values using the exact
    same logic the worker runs, without a second copy that could drift.

    Never raises: an unrecognized interruption_style (e.g. a config saved by
    a newer API version a worker hasn't caught up to yet) falls back to
    "balanced" rather than crashing the call.
    """
    style = config.get("interruption_style", "balanced")
    if style == "custom":
        balanced = INTERRUPTION_PRESETS["balanced"]
        return {
            "min_duration": config.get("interruption_min_duration", balanced.min_duration),
            "min_words": config.get("interruption_min_words", balanced.min_words),
            "false_interruption_timeout": config.get(
                "false_interruption_timeout", balanced.false_interruption_timeout
            ),
        }
    preset = INTERRUPTION_PRESETS.get(style, INTERRUPTION_PRESETS["balanced"])
    return {
        "min_duration": preset.min_duration,
        "min_words": preset.min_words,
        "false_interruption_timeout": preset.false_interruption_timeout,
    }


router = APIRouter(tags=["interruption-presets"])


@router.get("/interruption-presets")
async def list_interruption_presets(current_user: CurrentUser) -> dict:
    supported = adaptive_supported()
    return {
        "presets": [
            {
                "id": p.id,
                "label": p.label,
                "description": p.description,
                "min_duration": p.min_duration,
                "min_words": p.min_words,
                "false_interruption_timeout": p.false_interruption_timeout,
            }
            for p in INTERRUPTION_PRESETS.values()
        ],
        "adaptive_supported": supported,
        "adaptive_unsupported_reason": (
            None
            if supported
            else (
                "Adaptive detection requires STT_PROVIDER=livekit (streaming, "
                "word-aligned transcripts). This deployment is using the Groq "
                "STT fallback, which doesn't support it."
            )
        ),
    }
