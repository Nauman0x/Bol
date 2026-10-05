# Voice-agent latency

Measured from a Mac in India against LiveKit Cloud (region: India West) and
Groq's US datacenters, before any code changes:

| Stage | Measured |
|---|---|
| Bare `GET /models` to Groq US (warm, pooled connection) | 366ms median |
| Groq LLM time-to-first-*speakable*-token | 368ms |
| Groq batch STT (5s utterance, non-streaming) | ~360ms |
| Groq TTS time-to-first-byte | ~260ms (flat regardless of reply length — already streams) |
| Groq TTS real-time factor | 0.17–0.22 (≈5x faster than real time — generation throughput is not a bottleneck) |
| RTT to LiveKit Cloud edge (India West) | 158ms |
| RTT to Groq US | 315–356ms |

LLM time-to-first-token (368ms) is statistically identical to a no-op HTTP GET
to the same host (366ms) — proof that stage is ~100% network latency, ~0%
model compute. The end-to-end response time observed locally (~4s) came
almost entirely from configuration, not raw capability:

- Silero VAD's default `min_silence_duration` (0.55s) and the turn detector's
  default `max_delay` (3.0s, its worst-case stall when uncertain the caller
  is done) — both fixed, paid on every single turn regardless of network.
- The Groq model id in use (`qwen/qwen3.6-27b`) isn't in the groq plugin's
  built-in list of models that get `reasoning_effort="none"` automatically
  (that list only recognizes the old `qwen/qwen3-32b` id) — so it emitted a
  full `<think>` block before every reply. The framework strips `<think>`
  tags from what gets spoken, but the agent still waits through the entire
  reasoning generation first.
- Groq STT reports `capabilities.streaming = False`, so livekit-agents
  buffers the entire utterance and uploads it only *after* the caller stops
  talking — a fully serialized ~360ms added to every turn on top of
  whatever the endpointing delay already cost.

## What changed (`backend/worker/pipeline.py`, `backend/worker/agent.py`)

- `min_silence_duration` 0.55s → 0.3s
- Turn detector `min_delay` 0.5s → 0.25s, `max_delay` 3.0s → 1.2s
- `reasoning_effort="none"` passed explicitly to `groq.LLM`
- `preemptive_generation.preemptive_tts` enabled — speculative replies
  generated during the endpointing window can start TTS before turn-commit
- **STT switched to LiveKit's streaming inference gateway** (`STT_PROVIDER=livekit`,
  now the default) — `deepgram/flux-general-en` for English,
  `assemblyai/universal-streaming-multilingual` otherwise. This removes the
  serialized ~360ms Groq batch-STT round trip *and* moves that stage from
  Groq's US edge (356ms RTT) to LiveKit's own edge (158ms RTT). `STT_PROVIDER=groq`
  remains available as a fallback.
- Per-turn latency (`e2e_latency`, `llm_node_ttft`, `tts_node_ttfb`, etc.) is
  now logged and attached to `call_events` so this isn't guessed at again —
  see the `conversation_item_added` handler in `worker/agent.py`.
- Connection warmup for Groq's LLM/TTS turned out to already be automatic:
  `AgentSession.start()` schedules `AgentActivity._update_activity`, which
  calls `.prewarm()` on the resolved STT/LLM/TTS. For Groq's LLM and TTS
  (both extend the OpenAI plugin base classes) that fires a real token-free
  warmup request before the caller's first turn — confirmed by reading
  `voice/agent_activity.py` and `plugins/openai/{llm,tts}.py` in the
  installed package, not assumed. No additional code was needed.

## Deliberately unchanged

- **LLM and TTS provider stay on Groq.** LiveKit's inference gateway's LLM
  catalog is proprietary-only (OpenAI/Google/xAI/Moonshot/DeepSeek/GLM/xAI) —
  no Qwen — and Qwen3 is the model BOL is built around specifically for
  its open-weight tool-calling + Arabic strength (see `docs/RESEARCH.md`).
  Groq TTS (Orpheus) is likewise open-weight and already streams well
  (RTF 0.17–0.22). Trading that architectural commitment for ~200ms that
  deployment location recovers anyway isn't worth it.
- **Not switching to self-hosted Chatterbox.** `TTS_PROVIDER=local` is an
  unimplemented Phase 6 stub (`build_tts` raises `NotImplementedError`) — no
  Chatterbox/torch is installed. On Apple Silicon (MPS, no CUDA) a local
  Chatterbox swap would very likely be *slower* than hosted Groq: community
  streaming forks quote ~0.5s to first chunk on an RTX 4090, well behind the
  0.26s TTFB Groq already delivers today.

## Why 500ms wasn't reached locally, and what closes the gap

Three serialized cloud round trips (STT → LLM → TTS) impose a **~1s network
floor** on a machine this far from Groq's US datacenters — code changes
cannot remove physical distance. The path to 500ms is deploying the worker
process to a **US region near Groq**, where RTT drops from ~350ms to
~10–30ms. Expected post-deployment budget:

```
endpointing (min_delay)     0.25s
streaming STT final         ~0.10s
LLM time-to-first-token     ~0.06s   (was 368ms from India; ~10-30ms RTT + compute when co-located)
TTS time-to-first-byte      ~0.06s   (was 260ms from India; same)
──────────────────────────────────
total                       ~0.5s
```

This is a deployment requirement, not a code task — tracked here so it
doesn't get rediscovered as "still slow" after a future round of local
testing from a location far from Groq.

## Interruption handling (`backend/app/interruption.py`, `backend/worker/interruption.py`)

Barge-in is a per-agent setting (`AgentConfig.interruption_style`), not a
single global tuning. Presets, source of truth in `app/interruption.py`:

| style | min_duration | min_words | false_interruption_timeout |
|---|---|---|---|
| instant | 0.15s | 0 | 1.0s |
| **balanced** (default) | 0.3s | 0 | 2.0s |
| patient | 0.6s | 2 | 2.5s |
| custom | explicit per-agent fields | | |

"balanced" reproduces the values every agent ran with before per-agent
interruption settings existed — every agent saved before this feature keeps
behaving identically (see `test_pipeline.py`'s regression-lock test).

**Adaptive detection** (`interruption_mode: "adaptive"`) swaps simple VAD
barge-in for an ML backchannel classifier that tells "mhm"/"yeah" apart from
a genuine interruption — at the cost of extra LiveKit inference per call. It
requires a streaming, word-aligned STT (`STT_PROVIDER=livekit`); on the
Groq STT fallback, `build_turn_handling` silently downgrades it to `vad`
with a logged warning, and the worker reports an
`adaptive_interruption_unavailable` status event on the call timeline so
it's visible without grepping worker logs.

**Reading the telemetry**: every call's `latency_stats.interruptions` (when
present — omitted for calls with no barge-in activity at all) reports:

```
{ "true": <genuine interruptions>, "false": <turned out to be nothing>,
  "resumed": <false interruptions the agent auto-resumed>,
  "acked": <times ack_on_interrupt spoke "Go ahead.">,
  "connector": <times resume_style="connector" fired>,
  "style": <preset in effect>, "mode_effective": <vad|adaptive, post-downgrade> }
```

A high `false` count relative to `true` on a given agent is the signal to
move it from `instant`/`balanced` toward `patient`, or to turn on adaptive
detection if the deployment supports it — this is meant to replace guessing
at thresholds with a number.

`resume_style: "connector"` (re-generate the reply behind a spoken "sorry,
as I was saying" instead of the framework's silent mid-word resume) is
implemented but defaults off: the framework has already resumed and started
playing before our handler can intervene, so it adds a visible clip plus a
full extra LLM+TTS round trip on top of the timeout the caller already sat
through. The bigger, cheaper win for the same "sounds robotic" complaint is
just shortening `false_interruption_timeout` (as the `instant` preset does)
— see `worker/interruption.py` for the full tradeoff.
