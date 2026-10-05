"""Rough per-call cost estimate — figures sourced from docs/RESEARCH.md's
"Cost reality" section (~$0.008/min STT, ~$0.001-0.003/min LLM,
~$0.02-0.04/min TTS, ~$0.005-0.01/min telephony). Approximate on purpose:
real per-minute pricing varies by provider tier and region, and this isn't
meant to be billing-grade — just a directional number for the analytics
dashboard that reflects BOL's cost-vs-Vapi/Retell/Bland positioning.
"""

_STT_PER_MIN = 0.008
_LLM_PER_MIN = 0.002
_TELEPHONY_PER_MIN = 0.008
_TTS_PER_MIN = {
    "groq": 0.02,
    "fish": 0.04,
    # Self-hosted — nominal compute cost, not metered per-minute like the
    # hosted providers above.
    "chatterbox": 0.002,
}
_DEFAULT_TTS_PER_MIN = 0.03


def estimate_cost(duration_sec: int, transport: str | None, tts_provider: str | None) -> float:
    minutes = duration_sec / 60
    tts_rate = _TTS_PER_MIN.get(tts_provider or "", _DEFAULT_TTS_PER_MIN)
    rate = _STT_PER_MIN + _LLM_PER_MIN + tts_rate
    if transport == "telephony":
        rate += _TELEPHONY_PER_MIN
    return round(minutes * rate, 4)
