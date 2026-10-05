from worker.latency import LatencyCollector


def test_record_turn_extracts_only_relevant_keys_per_role():
    collector = LatencyCollector()

    user_timings = collector.record_turn(
        "user",
        {
            "transcription_delay": 0.123456,
            "end_of_turn_delay": 0.2,
            "e2e_latency": 999.0,  # assistant-only key, must be ignored for a user turn
        },
    )
    assert user_timings == {"transcription_delay": 0.123, "end_of_turn_delay": 0.2}

    assistant_timings = collector.record_turn(
        "assistant",
        {
            "e2e_latency": 0.8,
            "tts_node_ttfb": 0.15,
            "transcription_delay": 999.0,  # user-only key, must be ignored
        },
    )
    assert assistant_timings == {"e2e_latency": 0.8, "tts_node_ttfb": 0.15}


def test_summary_is_none_with_no_assistant_turns():
    collector = LatencyCollector()
    collector.record_turn("user", {"transcription_delay": 0.1})
    assert collector.summary() is None
    assert collector.headline_ms() == (None, None)


def test_summary_computes_percentiles_over_known_series():
    collector = LatencyCollector()
    # 1.0s through 10.0s — easy to reason about percentiles by hand.
    for value in [i / 10 for i in range(10, 101, 10)]:
        collector.record_turn("assistant", {"e2e_latency": value})

    summary = collector.summary()
    assert summary["turn_count"] == 10
    e2e = summary["stages"]["e2e_latency"]
    assert e2e["count"] == 10
    assert e2e["min"] == 1.0
    assert e2e["max"] == 10.0
    assert e2e["avg"] == 5.5
    # p50/p95 come from statistics.quantiles(n=100) — sanity-check they land
    # in the right neighborhood rather than asserting an exact float.
    assert 5.0 <= e2e["p50"] <= 6.0
    assert 9.0 <= e2e["p95"] <= 10.0


def test_summary_single_sample_p50_equals_p95_equals_max():
    collector = LatencyCollector()
    collector.record_turn("assistant", {"e2e_latency": 0.42})
    stats = collector.summary()["stages"]["e2e_latency"]
    assert stats["p50"] == stats["p95"] == stats["max"] == 0.42


def test_headline_ms_converts_seconds_to_rounded_milliseconds():
    collector = LatencyCollector()
    for value in (0.5, 1.5):
        collector.record_turn("assistant", {"e2e_latency": value})
    avg_ms, p95_ms = collector.headline_ms()
    assert avg_ms == 1000  # avg of 0.5s/1.5s = 1.0s = 1000ms
    assert isinstance(avg_ms, int)
    assert isinstance(p95_ms, int)


def test_provider_metadata_is_captured_once_per_stage():
    collector = LatencyCollector()
    collector.record_turn(
        "assistant",
        {
            "e2e_latency": 0.5,
            "tts_metadata": {"model_name": "s2.1-pro-free", "model_provider": "FishAudio"},
            "llm_metadata": {"model_name": "qwen/qwen3.6-27b", "model_provider": "Groq"},
        },
    )
    summary = collector.summary()
    assert summary["providers"] == {
        "tts_model": "s2.1-pro-free",
        "tts_provider": "FishAudio",
        "llm_model": "qwen/qwen3.6-27b",
        "llm_provider": "Groq",
    }


def test_provider_metadata_missing_keys_are_skipped_not_erroring():
    collector = LatencyCollector()
    collector.record_turn("assistant", {"e2e_latency": 0.5, "tts_metadata": {}})
    summary = collector.summary()
    assert summary["providers"] == {}


# --- interruption telemetry ---


def test_interruption_counters_appear_in_summary():
    collector = LatencyCollector()
    collector.record_turn("assistant", {"e2e_latency": 0.5})
    collector.record_interruption("true")
    collector.record_interruption("true")
    collector.record_interruption("false")
    collector.record_interruption("resumed")
    collector.record_interruption("acked")
    collector.record_interruption("connector")
    collector.set_interruption_config("balanced", "vad")

    summary = collector.summary()
    assert summary["interruptions"] == {
        "true": 2,
        "false": 1,
        "resumed": 1,
        "acked": 1,
        "connector": 1,
        "style": "balanced",
        "mode_effective": "vad",
    }


def test_summary_not_none_with_only_interruption_data():
    # A call where the caller barges into the greeting and hangs up has no
    # completed assistant turn (no e2e_latency sample) but does have
    # interruption data — that's still worth keeping, unlike the
    # no-data-at-all case in test_summary_is_none_with_no_assistant_turns.
    collector = LatencyCollector()
    collector.record_interruption("false")
    summary = collector.summary()
    assert summary is not None
    assert summary["turn_count"] == 0
    assert summary["interruptions"]["false"] == 1


def test_summary_omits_interruptions_key_when_never_recorded():
    collector = LatencyCollector()
    collector.record_turn("assistant", {"e2e_latency": 0.5})
    summary = collector.summary()
    assert "interruptions" not in summary


def test_headline_ms_unaffected_by_interruption_counters():
    collector = LatencyCollector()
    for value in (0.5, 1.5):
        collector.record_turn("assistant", {"e2e_latency": value})
    collector.record_interruption("true")
    avg_ms, p95_ms = collector.headline_ms()
    assert avg_ms == 1000
