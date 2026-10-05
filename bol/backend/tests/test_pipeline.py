import pytest

from app.config import settings
from worker.pipeline import (
    build_background_audio,
    build_instructions,
    build_noise_cancellation,
    build_stt,
    build_tts,
    build_turn_handling,
)

BASE_CONFIG = {
    "system_prompt": "You are a helpful receptionist.",
    "voice_id": "default",
}


def test_build_tts_defaults_to_groq(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gk_test")
    monkeypatch.setattr(settings, "tts_provider", "groq")
    tts = build_tts(BASE_CONFIG)
    assert type(tts).__module__.startswith("livekit.plugins.groq")
    assert tts.capabilities.streaming is False


def test_build_tts_fish_provider_streams(monkeypatch):
    monkeypatch.setattr(settings, "fish_api_key", "fish_test")
    tts = build_tts({**BASE_CONFIG, "tts_provider": "fish"})
    assert type(tts).__module__.startswith("livekit.plugins.fishaudio")
    assert tts.capabilities.streaming is True


def test_build_tts_chatterbox_provider_does_not_stream(monkeypatch):
    monkeypatch.setattr(settings, "chatterbox_base_url", "http://gpu-host:8004/v1")
    tts = build_tts({**BASE_CONFIG, "tts_provider": "chatterbox"})
    assert type(tts).__module__ == "worker.chatterbox_tts"
    # Framework-level capabilities.streaming is still False (no incremental
    # text input, see worker/chatterbox_tts.py) even though the HTTP
    # response itself streams — that response-level streaming is what
    # replaced the old buffered-mp3-via-openai-plugin approach.
    assert tts.capabilities.streaming is False


def test_build_tts_chatterbox_passes_language_through(monkeypatch):
    monkeypatch.setattr(settings, "chatterbox_base_url", "http://gpu-host:8004/v1")
    tts = build_tts({**BASE_CONFIG, "tts_provider": "chatterbox", "language": "es"})
    assert tts._opts.language == "es"


def test_build_tts_chatterbox_auto_language_passes_none(monkeypatch):
    monkeypatch.setattr(settings, "chatterbox_base_url", "http://gpu-host:8004/v1")
    tts = build_tts({**BASE_CONFIG, "tts_provider": "chatterbox", "language": "auto"})
    assert tts._opts.language is None


def test_build_tts_fish_without_key_raises_clear_error(monkeypatch):
    monkeypatch.setattr(settings, "fish_api_key", "")
    with pytest.raises(RuntimeError, match="FISH_API_KEY"):
        build_tts({**BASE_CONFIG, "tts_provider": "fish"})


def test_build_tts_chatterbox_without_url_raises_clear_error(monkeypatch):
    monkeypatch.setattr(settings, "chatterbox_base_url", "")
    with pytest.raises(RuntimeError, match="CHATTERBOX_BASE_URL"):
        build_tts({**BASE_CONFIG, "tts_provider": "chatterbox"})


def test_build_tts_agent_override_beats_platform_default(monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "groq")
    monkeypatch.setattr(settings, "fish_api_key", "fish_test")
    tts = build_tts({**BASE_CONFIG, "tts_provider": "fish"})
    assert type(tts).__module__.startswith("livekit.plugins.fishaudio")


def test_build_tts_groq_legacy_voice_aliases_still_work(monkeypatch):
    # "default"/"ar-default" were served by the /voices catalog before it
    # was fixed to list real Groq voice ids — agents saved under those
    # values must still resolve to a real voice, not error.
    monkeypatch.setattr(settings, "groq_api_key", "gk_test")
    default_tts = build_tts({**BASE_CONFIG, "voice_id": "default"})
    assert default_tts._opts.voice == "autumn"
    assert default_tts.model == "canopylabs/orpheus-v1-english"

    ar_default_tts = build_tts({**BASE_CONFIG, "voice_id": "ar-default"})
    assert ar_default_tts._opts.voice == "noura"
    assert ar_default_tts.model == "canopylabs/orpheus-arabic-saudi"


def test_build_tts_groq_arabic_voice_uses_arabic_model(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gk_test")
    for voice in ("fahad", "sultan", "lulwa", "noura"):
        tts = build_tts({**BASE_CONFIG, "voice_id": voice})
        assert tts.model == "canopylabs/orpheus-arabic-saudi", voice


def test_build_tts_groq_english_voice_uses_english_model(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gk_test")
    for voice in ("autumn", "diana", "hannah", "austin", "daniel", "troy"):
        tts = build_tts({**BASE_CONFIG, "voice_id": voice})
        assert tts.model == "canopylabs/orpheus-v1-english", voice


def test_build_stt_livekit_english_boosts_keywords_via_deepgram_keyterm(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "livekit")
    monkeypatch.setattr(settings, "livekit_api_key", "lk_key")
    monkeypatch.setattr(settings, "livekit_api_secret", "lk_secret")
    stt = build_stt({**BASE_CONFIG, "language": "en", "boosted_keywords": ["BOL", "Telnyx"]})
    assert stt._opts.extra_kwargs == {"keyterm": ["BOL", "Telnyx"]}


def test_build_stt_livekit_non_english_boosts_keywords_via_assemblyai_keyterms_prompt(
    monkeypatch,
):
    monkeypatch.setattr(settings, "stt_provider", "livekit")
    monkeypatch.setattr(settings, "livekit_api_key", "lk_key")
    monkeypatch.setattr(settings, "livekit_api_secret", "lk_secret")
    stt = build_stt({**BASE_CONFIG, "language": "ar", "boosted_keywords": ["بول"]})
    assert stt._opts.extra_kwargs == {"keyterms_prompt": ["بول"]}


def test_build_stt_livekit_without_keywords_has_no_extra_kwargs(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "livekit")
    monkeypatch.setattr(settings, "livekit_api_key", "lk_key")
    monkeypatch.setattr(settings, "livekit_api_secret", "lk_secret")
    stt = build_stt({**BASE_CONFIG, "language": "en"})
    assert stt._opts.extra_kwargs == {}


def test_build_stt_livekit_non_english_uses_multilingual_model_for_any_language(monkeypatch):
    # Not just Arabic — any language outside "en" routes to the same
    # multilingual model, and Spanish specifically gets a language hint
    # passed through (see build_stt's language_kwargs).
    monkeypatch.setattr(settings, "stt_provider", "livekit")
    monkeypatch.setattr(settings, "livekit_api_key", "lk_key")
    monkeypatch.setattr(settings, "livekit_api_secret", "lk_secret")
    stt = build_stt({**BASE_CONFIG, "language": "es"})
    assert stt.model == "assemblyai/universal-streaming-multilingual"
    assert stt._opts.language == "es"


def test_build_stt_livekit_auto_language_passes_no_hint(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "livekit")
    monkeypatch.setattr(settings, "livekit_api_key", "lk_key")
    monkeypatch.setattr(settings, "livekit_api_secret", "lk_secret")
    stt = build_stt({**BASE_CONFIG, "language": "auto"})
    # NOT_GIVEN when no explicit language was passed — auto-detect stays on.
    from livekit.agents.types import NOT_GIVEN

    assert stt._opts.language is NOT_GIVEN


def test_build_stt_livekit_boosts_keywords_for_any_non_english_language(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "livekit")
    monkeypatch.setattr(settings, "livekit_api_key", "lk_key")
    monkeypatch.setattr(settings, "livekit_api_secret", "lk_secret")
    stt = build_stt({**BASE_CONFIG, "language": "fr", "boosted_keywords": ["BOL"]})
    assert stt._opts.extra_kwargs == {"keyterms_prompt": ["BOL"]}


def test_build_noise_cancellation_differs_by_transport():
    # Telephony (narrowband PSTN) and webrtc (browser mic) use different
    # bundled models — exact filenames aren't public API, just assert they
    # resolve to distinct, real files.
    telephony_nc = build_noise_cancellation("telephony")
    webrtc_nc = build_noise_cancellation("webrtc")
    assert telephony_nc.options["modelPath"].endswith(".kef")
    assert webrtc_nc.options["modelPath"].endswith(".kef")
    assert telephony_nc.options["modelPath"] != webrtc_nc.options["modelPath"]


def test_build_instructions_streaming_drops_opener_hint():
    streaming = build_instructions(BASE_CONFIG, streaming_tts=True)
    non_streaming = build_instructions(BASE_CONFIG, streaming_tts=False)
    assert "short opening acknowledgment" not in streaming
    assert "short opening acknowledgment" in non_streaming
    assert streaming.endswith(BASE_CONFIG["system_prompt"])
    assert non_streaming.endswith(BASE_CONFIG["system_prompt"])


def test_build_background_audio_none_when_unconfigured():
    assert build_background_audio(BASE_CONFIG) is None


async def test_build_background_audio_builtin_clip():
    # BackgroundAudioPlayer's constructor spins up an rtc.AudioMixer, which
    # needs a running event loop — hence async def here.
    player = build_background_audio({**BASE_CONFIG, "ambience": "office"})
    assert player is not None


async def test_build_background_audio_applies_per_clip_gain_compensation():
    # office-ambience is mastered ~23x quieter than the loudness-normalized
    # baseline (measured directly off the bundled .ogg — see
    # pipeline.py:_BUILTIN_AMBIENCE_GAIN) — without compensation,
    # ambience_volume=1.0 would still be almost silent. Regression test for
    # that bug.
    from worker.pipeline import _BUILTIN_AMBIENCE_GAIN

    player = build_background_audio(
        {**BASE_CONFIG, "ambience": "office", "ambience_volume": 1.0}
    )
    assert player._ambient_sound.volume == _BUILTIN_AMBIENCE_GAIN["office"]

    player_half = build_background_audio(
        {**BASE_CONFIG, "ambience": "office", "ambience_volume": 0.5}
    )
    assert player_half._ambient_sound.volume == _BUILTIN_AMBIENCE_GAIN["office"] * 0.5


async def test_build_background_audio_custom_clip_is_not_gain_compensated(tmp_path):
    # Unlike builtin clips, there's no loudness data for a user upload — it
    # must play at ambience_volume as a direct multiplier, not scaled by any
    # builtin gain table.
    clip_path = tmp_path / "clip.wav"
    clip_path.write_bytes(b"not-real-audio-but-path-is-what-matters")
    player = build_background_audio(
        {**BASE_CONFIG, "ambience": "custom:abc123", "ambience_volume": 0.7},
        custom_clip_path=str(clip_path),
    )
    assert player._ambient_sound.volume == 0.7


def test_build_background_audio_unknown_builtin_key_is_noop():
    assert build_background_audio({**BASE_CONFIG, "ambience": "not-a-real-clip"}) is None


def test_build_background_audio_custom_without_downloaded_path_is_noop():
    # ambience is "custom:<id>" but the caller's download failed or timed
    # out (custom_clip_path=None) — must degrade silently, not error.
    result = build_background_audio(
        {**BASE_CONFIG, "ambience": "custom:abc123"}, custom_clip_path=None
    )
    assert result is None


async def test_build_background_audio_custom_with_downloaded_path(tmp_path):
    clip_path = tmp_path / "clip.wav"
    clip_path.write_bytes(b"not-real-audio-but-path-is-what-matters")
    player = build_background_audio(
        {**BASE_CONFIG, "ambience": "custom:abc123"}, custom_clip_path=str(clip_path)
    )
    assert player is not None


async def test_build_background_audio_thinking_sound_only():
    player = build_background_audio({**BASE_CONFIG, "thinking_sound": True})
    assert player is not None


# --- build_turn_handling ---


def test_build_turn_handling_matches_pre_settings_hardcoded_behavior():
    # Regression lock: before per-agent interruption settings existed,
    # worker/agent.py hardcoded exactly this dict. Every agent saved before
    # this feature has none of the new config keys and must keep resolving
    # to these exact values.
    assert build_turn_handling(BASE_CONFIG) == {
        "endpointing": {"mode": "dynamic", "min_delay": 0.25, "max_delay": 1.2},
        "interruption": {
            "enabled": True,
            "mode": "vad",
            "min_duration": 0.3,
            "min_words": 0,
            "false_interruption_timeout": 2.0,
        },
        "preemptive_generation": {"preemptive_tts": True},
    }


def test_build_turn_handling_instant_preset():
    result = build_turn_handling({**BASE_CONFIG, "interruption_style": "instant"})
    assert result["interruption"]["min_duration"] == 0.15
    assert result["interruption"]["min_words"] == 0
    assert result["interruption"]["false_interruption_timeout"] == 1.0


def test_build_turn_handling_patient_preset():
    result = build_turn_handling({**BASE_CONFIG, "interruption_style": "patient"})
    assert result["interruption"]["min_duration"] == 0.6
    assert result["interruption"]["min_words"] == 2
    assert result["interruption"]["false_interruption_timeout"] == 2.5


def test_build_turn_handling_unknown_style_falls_back_to_balanced():
    # A config saved by a newer API a worker hasn't caught up to yet must
    # never crash the call.
    result = build_turn_handling({**BASE_CONFIG, "interruption_style": "aggressive"})
    assert result["interruption"]["min_duration"] == 0.3
    assert result["interruption"]["false_interruption_timeout"] == 2.0


def test_build_turn_handling_custom_reads_explicit_fields():
    result = build_turn_handling(
        {
            **BASE_CONFIG,
            "interruption_style": "custom",
            "interruption_min_duration": 0.8,
            "interruption_min_words": 3,
            "false_interruption_timeout": 4.0,
        }
    )
    assert result["interruption"]["min_duration"] == 0.8
    assert result["interruption"]["min_words"] == 3
    assert result["interruption"]["false_interruption_timeout"] == 4.0


def test_build_turn_handling_custom_without_explicit_fields_falls_back_to_balanced():
    result = build_turn_handling({**BASE_CONFIG, "interruption_style": "custom"})
    assert result["interruption"]["min_duration"] == 0.3
    assert result["interruption"]["min_words"] == 0
    assert result["interruption"]["false_interruption_timeout"] == 2.0


def test_build_turn_handling_interruption_disabled_still_resolves_preset():
    result = build_turn_handling({**BASE_CONFIG, "interruption_enabled": False})
    assert result["interruption"]["enabled"] is False
    assert result["interruption"]["min_duration"] == 0.3


def test_build_turn_handling_adaptive_downgrades_on_non_livekit_stt(monkeypatch, caplog):
    monkeypatch.setattr(settings, "stt_provider", "groq")
    with caplog.at_level("WARNING"):
        result = build_turn_handling({**BASE_CONFIG, "interruption_mode": "adaptive"})
    assert result["interruption"]["mode"] == "vad"
    assert "adaptive" in caplog.text.lower()


def test_build_turn_handling_adaptive_allowed_on_livekit_stt(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "livekit")
    result = build_turn_handling({**BASE_CONFIG, "interruption_mode": "adaptive"})
    assert result["interruption"]["mode"] == "adaptive"


def test_build_turn_handling_endpointing_and_preemptive_unaffected_by_interruption_settings():
    result = build_turn_handling(
        {
            **BASE_CONFIG,
            "interruption_style": "patient",
            "interruption_mode": "adaptive",
            "ack_on_interrupt": True,
            "resume_style": "connector",
        }
    )
    assert result["endpointing"] == {"mode": "dynamic", "min_delay": 0.25, "max_delay": 1.2}
    assert result["preemptive_generation"] == {"preemptive_tts": True}
