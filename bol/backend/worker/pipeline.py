"""Assembles the VAD/STT/LLM/TTS pipeline from an agent's config.

STT is selected by STT_PROVIDER so a self-hosted faster-whisper service can be
swapped in with an env change only. TTS is selected per-agent
(config["tts_provider"]) falling back to the platform-wide TTS_PROVIDER —
nothing in worker/agent.py needs to know which provider is active.
"""

import logging

from livekit import rtc
from livekit.agents import (
    AudioConfig,
    BackgroundAudioPlayer,
    BuiltinAudioClip,
    inference,
)
from livekit.agents import stt as stt_base
from livekit.agents import tts as tts_base
from livekit.agents import vad as vad_base
from livekit.agents.llm import LLM
from livekit.plugins import fishaudio, groq, noise_cancellation, silero

from app.config import settings
from app.interruption import adaptive_supported, resolve_interruption
from app.tts_providers import resolve_llm_model, resolve_tts_provider
from worker.chatterbox_tts import ChatterboxTTS

logger = logging.getLogger("BOL.worker")

# "default"/"ar-default" were served by the /voices catalog before it was
# fixed to list the real Groq voice ids — these two aliases keep agents
# saved under the old values working instead of erroring on an invalid
# voice name. New agents never see these; the catalog only offers real ids.
_LEGACY_GROQ_VOICE_ALIASES = {"default": "autumn", "ar-default": "noura"}

# Voices that speak Arabic — must be paired with the Arabic model below, or
# Groq silently renders them on the English model instead. groq.TTS's
# `model` param defaults to a plain string (not NotGivenOr), so both branches
# must be real model ids — there's no "leave it unset" option here.
#
# Orpheus (Groq's TTS) genuinely only ships English and Arabic models —
# there is no third language to route to. An agent configured for any other
# language should use tts_provider "fish" (per-voice, any language) or
# "chatterbox" (self-hosted, 23 languages) instead; see /tts-providers and
# the voices catalog (app/routers/voices.py) for what's actually available.
_GROQ_ARABIC_VOICES = {"fahad", "sultan", "lulwa", "noura"}
_GROQ_ARABIC_MODEL = "canopylabs/orpheus-arabic-saudi"
_GROQ_ENGLISH_MODEL = "canopylabs/orpheus-v1-english"

_BUILTIN_AMBIENCE = {
    "office": BuiltinAudioClip.OFFICE_AMBIENCE,
    "city": BuiltinAudioClip.CITY_AMBIENCE,
    "forest": BuiltinAudioClip.FOREST_AMBIENCE,
    "crowded_room": BuiltinAudioClip.CROWDED_ROOM,
    "hold_music": BuiltinAudioClip.HOLD_MUSIC,
}

# LiveKit's bundled clips are mastered at wildly different native loudness
# (measured peak/RMS on the actual .ogg files: office-ambience -37dBFS peak
# vs hold_music -0.5dBFS peak — a ~40dB spread). AudioConfig(volume=1.0) is
# *unity gain*, not "full loudness" — it passes the clip through unchanged —
# so without this table, ambience_volume=1.0 on office-ambience is still
# nearly silent while hold_music at the same setting is nearly clipping.
# Each factor below normalizes its clip to ~-28dBFS RMS at ambience_volume=1.0,
# capped so peak never exceeds -0.9dBFS at that setting — ambience_volume can
# go up to 1.5 (see AgentConfig.ambience_volume) for louder-than-baseline,
# which may clip on the louder clips; that's an acceptable tradeoff for an
# explicit "louder" choice. Recompute if LiveKit ever changes these files.
_BUILTIN_AMBIENCE_GAIN = {
    "office": 23.34,
    "city": 1.93,
    "forest": 13.79,
    "crowded_room": 0.79,
    "hold_music": 0.25,
}
_THINKING_SOUND_GAIN = 1.72  # both keyboard-typing clips, same measurement

_THINKING_SOUNDS = [
    AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=0.6 * _THINKING_SOUND_GAIN),
    AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING2, volume=0.5 * _THINKING_SOUND_GAIN),
]

# The opener-phrase instruction below only matters for non-streaming TTS
# (see build_instructions) — livekit-agents buffers a full sentence before
# synthesis starts, so without a short opener the caller waits through the
# whole first sentence before hearing anything.
_STREAMING_TTS_PREAMBLE = (
    "You are on a live phone call. Always speak in the same language the caller is "
    "using. Keep responses short — under 3 sentences unless the caller asks for "
    "detail. Never read out URLs or spell out long strings (codes, ids, emails) "
    "unless the caller explicitly asks you to. Speak naturally, the way a person "
    "would on the phone.\n\n"
)
_NON_STREAMING_TTS_PREAMBLE = (
    "You are on a live phone call. Always speak in the same language the caller is "
    "using. Keep responses short — under 3 sentences unless the caller asks for "
    "detail. Never read out URLs or spell out long strings (codes, ids, emails) "
    "unless the caller explicitly asks you to. Speak naturally, the way a person "
    "would on the phone. Start every reply with a short opening acknowledgment "
    "(2-5 words, in the caller's language) before the rest of your answer — "
    "text-to-speech synthesizes one sentence at a time, so a short opener "
    "gets audio playing sooner instead of making the caller wait through a long "
    "first sentence.\n\n"
)


def build_vad() -> vad_base.VAD:
    # Default min_silence_duration (0.55s) is the single biggest fixed cost in
    # the turn-taking latency budget — every reply waits this long after the
    # caller stops talking before anything downstream even starts. 0.3s still
    # comfortably exceeds normal mid-sentence pauses.
    return silero.VAD.load(min_silence_duration=0.3)


def build_turn_handling(config: dict) -> dict:
    """AgentSession(turn_handling=...) — endpointing, interruption, and
    preemptive-generation settings, in one place so they're testable without
    constructing a real AgentSession (see test_pipeline.py).

    Defaults (min_delay=0.5s, max_delay=3.0s) mean every reply pays at
    least 0.5s of dead air, and the turn-detector can stall a full 3s
    when it's unsure the caller is done — measured as the single
    largest source of the ~4s response time. 0.25/1.2 keeps the
    detector's benefit (still escalates when genuinely unsure) without
    the worst-case stall. preemptive_tts lets speculative LLM replies
    (already generated during the endpointing window) start TTS before
    turn-commit instead of after.

    mode="dynamic" is required for max_delay to do anything at all —
    EndpointingOptions defaults to mode="fixed", which only reads
    min_delay and ignores max_delay entirely (confirmed against the
    installed livekit-agents source, voice/turn.py). Without this the
    comment above was describing behavior the config never actually
    produced: every turn waited the fixed 0.25s regardless of
    confidence, dynamic escalation up to 1.2s never happened.
    """
    resolved = resolve_interruption(config)
    mode = config.get("interruption_mode", "vad")
    if mode == "adaptive" and not adaptive_supported():
        # STT_PROVIDER=groq (or any future non-streaming provider) can't
        # gatekeep transcripts for the adaptive detector — silently asking
        # for it anyway would either error deep in the framework or (per
        # voice/agent_activity.py's _resolve_interruption_detection) just
        # log an INFO line nobody watches. Downgrade loudly instead; the
        # caller (worker/agent.py) also reports this on the call timeline.
        logger.warning(
            "interruption_mode=adaptive requested but STT_PROVIDER=%s doesn't "
            "support it (needs a streaming, word-aligned STT) — using vad instead",
            settings.stt_provider,
        )
        mode = "vad"

    return {
        "endpointing": {"mode": "dynamic", "min_delay": 0.25, "max_delay": 1.2},
        "interruption": {
            "enabled": config.get("interruption_enabled", True),
            "mode": mode,
            "min_duration": resolved["min_duration"],
            "min_words": resolved["min_words"],
            "false_interruption_timeout": resolved["false_interruption_timeout"],
        },
        "preemptive_generation": {"preemptive_tts": True},
    }


def _require_groq_key() -> str:
    if not settings.groq_api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not configured. The livekit-plugins-groq constructors "
            "are given the key explicitly (not via os.getenv) because "
            "pydantic-settings loads it into app.config.settings only, never into "
            "the process environment — so the plugin's own env fallback can't see it."
        )
    return settings.groq_api_key


def _require_livekit_creds() -> tuple[str, str]:
    if not settings.livekit_api_key or not settings.livekit_api_secret:
        raise RuntimeError("LIVEKIT_API_KEY/LIVEKIT_API_SECRET are not configured")
    return settings.livekit_api_key, settings.livekit_api_secret


def _require_fish_key() -> str:
    if not settings.fish_api_key:
        raise RuntimeError(
            "FISH_API_KEY is not configured but an agent's tts_provider (or the "
            "platform-wide TTS_PROVIDER) is 'fish'. Passed explicitly, same reason "
            "as _require_groq_key above."
        )
    return settings.fish_api_key


def _require_chatterbox_url() -> str:
    if not settings.chatterbox_base_url:
        raise RuntimeError(
            "CHATTERBOX_BASE_URL is not configured but an agent's tts_provider (or "
            "the platform-wide TTS_PROVIDER) is 'chatterbox'. Point it at a "
            "self-hosted Chatterbox-TTS-Server instance — see deploy/chatterbox/."
        )
    return settings.chatterbox_base_url


def build_stt(config: dict) -> stt_base.STT:
    if settings.stt_provider == "local":
        raise NotImplementedError(
            "STT_PROVIDER=local requires the Phase 6 self-hosted faster-whisper service."
        )
    language = config.get("language", "en")

    if settings.stt_provider == "livekit":
        # Groq STT reports capabilities.streaming=False — livekit-agents wraps
        # it in a StreamAdapter that buffers the whole utterance and uploads
        # it only after the caller stops talking (~360ms serialized on the
        # critical path, measured). LiveKit's inference gateway offers real
        # streaming STT that also lands on LiveKit's edge instead of Groq's
        # US datacenters (158ms RTT vs 356ms, measured from this machine).
        # flux-general-en is English-only and tuned for low-latency
        # conversational turn detection; every other language (including
        # "auto") uses the multilingual model — chosen once here, everything
        # below (boosted-keyword key, language hint) is derived from it
        # rather than re-checking `language == "en"` separately, so those
        # two can't drift out of sync with the model choice.
        api_key, api_secret = _require_livekit_creds()
        is_flux = language == "en"
        model = (
            "deepgram/flux-general-en" if is_flux else "assemblyai/universal-streaming-multilingual"
        )

        # Deepgram Flux and AssemblyAI each take boosted vocabulary under a
        # different extra_kwargs key (see inference/stt.py's
        # DeepgramFluxOptions/AssemblyaiOptions) — no shared param name.
        keywords = config.get("boosted_keywords") or []
        extra_kwargs: dict = {}
        if keywords:
            extra_kwargs = {"keyterm": keywords} if is_flux else {"keyterms_prompt": keywords}

        # AssemblyAI's multilingual model auto-detects by default; passing
        # the configured language as a hint measurably improves accuracy
        # (especially for commonly-confused pairs like hi/ur) — but only
        # when the agent picked a specific language. "auto" means the agent
        # explicitly wants detection, so no hint is passed then. Flux is
        # English-only already, so this only matters on the non-Flux branch.
        language_kwargs = {} if is_flux or language == "auto" else {"language": language}

        return inference.STT(
            model=model,
            api_key=api_key,
            api_secret=api_secret,
            extra_kwargs=extra_kwargs,
            **language_kwargs,
        )

    api_key = _require_groq_key()
    if language == "auto":
        return groq.STT(model="whisper-large-v3-turbo", detect_language=True, api_key=api_key)
    return groq.STT(model="whisper-large-v3-turbo", language=language, api_key=api_key)


def build_llm(config: dict) -> LLM:
    # reasoning_effort="none" matters a lot here: the groq plugin only
    # auto-disables reasoning for the old "qwen/qwen3-32b" id, not the real
    # "qwen/qwen3.6-27b" one we use — without this the model "thinks" before
    # every reply (measured ~0.87s vs ~0.23s to first speakable token for the
    # same answer). The framework strips <think> tags from what gets spoken,
    # but the agent still waits through the entire reasoning generation first.
    return groq.LLM(
        model=resolve_llm_model(config),
        temperature=config.get("temperature", 0.7),
        api_key=_require_groq_key(),
        reasoning_effort="none",
        # A voice turn should be a sentence or two, not an essay — capping
        # this also matters for Groq's free-tier output-tokens-per-minute
        # limit (1000 OTPM as of writing for qwen3.8-27b): an uncapped
        # request can ask for enough tokens on its own to blow the whole
        # per-minute budget in one turn, then every retry adds seconds of
        # backoff on top (see the call latency investigation this fixed).
        max_completion_tokens=200,
    )


def build_tts(config: dict) -> tts_base.TTS:
    provider = resolve_tts_provider(config)
    voice_id = config.get("voice_id", "default")

    if provider == "fish":
        # latency_mode="balanced" trades a little consistency for speed vs
        # "normal" — see docs/RESEARCH.md. The plugin reports
        # capabilities.streaming=True (real WebSocket streaming, confirmed
        # against the installed package), so no StreamAdapter buffering,
        # unlike Groq/Chatterbox below. Constructor param is voice_id, not
        # Fish's own wire name reference_id — same value either way.
        return fishaudio.TTS(
            model=settings.fish_model,
            voice_id=voice_id,
            api_key=_require_fish_key(),
            latency_mode="balanced",
        )

    if provider == "chatterbox":
        # Custom plugin (worker/chatterbox_tts.py) against the server's
        # native streaming /tts endpoint — the OpenAI-compatible
        # /v1/audio/speech path (livekit-plugins-openai) buffers a whole
        # mp3 response before any audio plays; this streams raw PCM as the
        # server produces it. See deploy/chatterbox/README.md.
        language = config.get("language", "en")
        return ChatterboxTTS(
            base_url=_require_chatterbox_url(),
            voice_id=voice_id,
            # "auto" means "detect the caller's language", which the TTS
            # side can't do anything with — omit it and let the server fall
            # back to its own configured default rather than mislabeling.
            language=None if language == "auto" else language,
        )

    if provider == "local":
        raise NotImplementedError(
            "TTS_PROVIDER=local is not a real provider — use tts_provider='chatterbox' "
            "with CHATTERBOX_BASE_URL pointed at a self-hosted instance instead "
            "(see deploy/chatterbox/)."
        )

    # provider == "groq" (default). Both the voice AND the model must match
    # the language — passing an Arabic voice with the default English model
    # silently renders on the wrong model instead of erroring.
    groq_voice = _LEGACY_GROQ_VOICE_ALIASES.get(voice_id, voice_id)
    groq_model = (
        _GROQ_ARABIC_MODEL if groq_voice in _GROQ_ARABIC_VOICES else _GROQ_ENGLISH_MODEL
    )
    return groq.TTS(voice=groq_voice, model=groq_model, api_key=_require_groq_key())


def build_noise_cancellation(transport: str) -> rtc.NoiseCancellationOptions:
    # BVCTelephony is tuned for narrowband PSTN audio; plain BVC assumes the
    # fuller-band audio a browser mic captures. Both run on-device (bundled
    # native model, no cloud API/cost) — see livekit-plugins-noise-cancellation.
    if transport == "telephony":
        return noise_cancellation.BVCTelephony()
    return noise_cancellation.BVC()


def build_instructions(config: dict, streaming_tts: bool) -> str:
    preamble = _STREAMING_TTS_PREAMBLE if streaming_tts else _NON_STREAMING_TTS_PREAMBLE
    return preamble + config["system_prompt"]


def build_background_audio(
    config: dict, custom_clip_path: str | None = None
) -> BackgroundAudioPlayer | None:
    """None when there's nothing to play — callers should skip start()/aclose()
    entirely in that case.

    ambience is either a builtin key (see _BUILTIN_AMBIENCE) or
    "custom:<ambience_clip id>". For the custom case, custom_clip_path is a
    local file path the caller (worker/agent.py) has already downloaded —
    fetching it is async with a timeout there, so a slow/unreachable clip
    can never delay the greeting. If it's still None when this is called
    (download failed or timed out), ambience is silently skipped rather than
    blocking or erroring the call.
    """
    ambience = config.get("ambience")
    thinking_sound = config.get("thinking_sound", False)

    ambient_sound = None
    if ambience and ambience.startswith("custom:"):
        if custom_clip_path:
            # No loudness data for user uploads — unlike the builtin clips
            # below, there's nothing to normalize against, so this is
            # unity-gain passthrough (the upload's own native loudness).
            volume = config.get("ambience_volume", 0.2)
            ambient_sound = AudioConfig(
                custom_clip_path, volume=volume, fade_in=0.5, fade_out=0.5
            )
    elif ambience:
        clip = _BUILTIN_AMBIENCE.get(ambience)
        if clip is not None:
            volume = config.get("ambience_volume", 0.2) * _BUILTIN_AMBIENCE_GAIN[ambience]
            ambient_sound = AudioConfig(clip, volume=volume, fade_in=0.5, fade_out=0.5)

    if ambient_sound is None and not thinking_sound:
        return None

    return BackgroundAudioPlayer(
        ambient_sound=ambient_sound,
        thinking_sound=_THINKING_SOUNDS if thinking_sound else None,
    )
