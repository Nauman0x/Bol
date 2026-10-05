from app.services.cost import estimate_cost


def test_estimate_cost_telephony_groq():
    # 60s at (0.008 stt + 0.002 llm + 0.02 groq tts + 0.008 telephony)/min
    cost = estimate_cost(60, "telephony", "groq")
    assert cost == 0.038


def test_estimate_cost_webrtc_has_no_telephony_leg():
    webrtc = estimate_cost(60, "webrtc", "groq")
    telephony = estimate_cost(60, "telephony", "groq")
    assert webrtc < telephony


def test_estimate_cost_unknown_tts_provider_uses_default_rate():
    assert estimate_cost(60, "webrtc", "some-future-provider") == estimate_cost(
        60, "webrtc", None
    )


def test_estimate_cost_chatterbox_cheaper_than_hosted():
    assert estimate_cost(60, "webrtc", "chatterbox") < estimate_cost(60, "webrtc", "fish")


def test_estimate_cost_zero_duration():
    assert estimate_cost(0, "telephony", "groq") == 0.0
