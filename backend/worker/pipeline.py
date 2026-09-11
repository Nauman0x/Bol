"""STT/LLM/TTS plugin builders, gated by the AI_PROVIDER env var.

This is the seam between the zero-key "stub" pipeline (Phase 3a) and real AI
providers (Phase 3b, currently Groq). agent.py never imports a provider plugin
directly -- it only calls the build_* functions below, so adding a provider
later means editing this file only.
"""
import array
import asyncio
import math
import os
from collections.abc import AsyncIterator
from typing import Any

from livekit import rtc
from livekit.plugins import silero

AI_PROVIDER = os.environ.get("AI_PROVIDER", "stub")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_STT_MODEL = os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")
GROQ_TTS_MODEL = os.environ.get("GROQ_TTS_MODEL", "playai-tts")
DEFAULT_GROQ_LLM_MODEL = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")

VOICE_GUARDRAIL_PREAMBLE = (
    "You are in a live voice conversation. Keep responses under 3 sentences "
    "unless asked for detail. Speak naturally."
)

STUB_REPLY = "Thanks for calling — this is a test agent running in stub mode."


def build_vad() -> silero.VAD:
    # Real VAD always, in every mode -- it's local/free and ships with livekit-plugins-silero.
    return silero.VAD.load()


def build_stt(agent_config: dict[str, Any]):
    if AI_PROVIDER == "groq":
        from livekit.plugins import groq

        language = agent_config.get("language", "auto")
        if language == "auto":
            return groq.STT(model=GROQ_STT_MODEL, detect_language=True, api_key=GROQ_API_KEY or None)
        return groq.STT(model=GROQ_STT_MODEL, language=language, api_key=GROQ_API_KEY or None)
    return None


def build_llm(agent_config: dict[str, Any]):
    if AI_PROVIDER == "groq":
        from livekit.plugins import groq

        return groq.LLM(
            model=agent_config.get("llm_model") or DEFAULT_GROQ_LLM_MODEL,
            temperature=agent_config.get("temperature", 0.7),
            api_key=GROQ_API_KEY or None,
        )
    return None


def build_tts(agent_config: dict[str, Any]):
    if AI_PROVIDER == "groq":
        from livekit.plugins import groq

        return groq.TTS(
            model=GROQ_TTS_MODEL,
            voice=agent_config.get("voice_id") or "Cheyenne-PlayAI",
            api_key=GROQ_API_KEY or None,
        )
    return None


def build_instructions(agent_config: dict[str, Any]) -> str:
    return f"{VOICE_GUARDRAIL_PREAMBLE}\n\n{agent_config.get('system_prompt', '')}"


def _tone_pcm(duration_sec: float, sample_rate: int) -> bytes:
    n_samples = int(duration_sec * sample_rate)
    samples = array.array("h", [0] * n_samples)
    fade = max(1, sample_rate // 100)  # ~10ms fade to avoid clicks
    for i in range(n_samples):
        envelope = min(i / fade, (n_samples - i) / fade, 1.0)
        samples[i] = int(3000 * envelope * math.sin(2 * math.pi * 440.0 * i / sample_rate))
    return samples.tobytes()


async def synthesize_placeholder_audio(text: str) -> AsyncIterator[rtc.AudioFrame]:
    """Minimal built-in "synthesizer" used only in stub mode.

    Neither livekit-agents core nor livekit-plugins-silero ships a free/local TTS
    engine (Silero only provides VAD), so there is no real speech synthesis
    available with zero AI provider keys. Rather than leave stub mode unable to
    "speak" at all, this emits an audible placeholder tone (duration scaled to the
    text) so session.say(audio=...) has real audio to play, while the actual
    greeting/reply text still goes through the transcript and event reporting.
    """
    sample_rate = 16000
    duration_sec = max(0.6, min(4.0, 0.045 * len(text)))
    pcm = _tone_pcm(duration_sec, sample_rate)
    chunk_samples = sample_rate // 50  # 20ms chunks
    total_samples = len(pcm) // 2
    offset = 0
    while offset < total_samples:
        n = min(chunk_samples, total_samples - offset)
        chunk = pcm[offset * 2 : (offset + n) * 2]
        yield rtc.AudioFrame(data=chunk, sample_rate=sample_rate, num_channels=1, samples_per_channel=n)
        offset += n
        await asyncio.sleep(0)
