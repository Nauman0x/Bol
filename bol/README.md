# BOL — بول

**Open-source-first AI calling platform.** BOL — بول (Urdu for "speak") lets businesses run AI voice agents over real phone lines while owning as much of the stack as possible — self-hostable telephony, open-weight LLMs, and open-source speech models.

## Guiding principle

Minimize third-party paid services. Every layer is open source and self-hostable **except** the PSTN carrier — phone numbers and minutes legally require a licensed operator, but that dependency is reduced to a cheap wholesale SIP trunk (~$0.002–0.005/min) instead of a full CPaaS like Twilio.

## The stack (see [docs/RESEARCH.md](docs/RESEARCH.md) for why)

| Layer | Choice | License | Notes |
|---|---|---|---|
| Telephony / media | **LiveKit** server + `livekit/sip` bridge | Apache-2.0 | Self-hostable; also gives WebRTC (in-app calls, web widget) for free |
| Carrier (unavoidable) | **Telnyx** Elastic SIP trunk | — | DIDs ~$1/mo, minutes ~$0.002–0.005; 2nd carrier later for failover |
| Orchestration | **LiveKit Agents** (Python) | Apache-2.0 | STT→LLM→TTS pipeline, Silero VAD + turn detection for barge-in |
| LLM (MVP) | **Qwen3-32B on Groq** (hosted open weights) | Open weights | Sub-100ms TTFT; best open model for tool-calling **and** Arabic |
| LLM (scale) | Self-hosted Qwen3-32B on **SGLang**, 1× H100 | Apache-2.0 | ~$1.5k/mo, prefix caching suits repeated agent prompts |
| STT | **faster-whisper large-v3-turbo** (streaming server) | MIT | Best open Arabic accuracy; Parakeet TDT for English-only low latency |
| TTS | **Chatterbox Multilingual v3** | MIT | ~75–200ms first audio, voice cloning, native Arabic, beats ElevenLabs in blind tests |
| Frontend | `frontend/` — dashboard (agent builder, call logs, analytics) | — | TBD: Next.js/React |
| Backend | `backend/` — API + agent workers | — | Python (agents) + API layer |

## Architecture

```
PSTN caller ──▶ Telnyx SIP trunk ──▶ livekit/sip bridge ──▶ LiveKit server (SFU)
                                                                 │
                                                    agent joins room as participant
                                                                 ▼
                                            LiveKit Agents worker (Python)
                                     STT (faster-whisper) → LLM (Qwen3-32B via Groq)
                                     → TTS (Chatterbox) — with VAD/barge-in
```

Target voice-to-voice latency: **300–500ms** (natural-feeling threshold).

## Running locally

Calls — including browser test calls — need **two backend processes** running together, plus the frontend:

```bash
make dev      # FastAPI API — creates rooms/dispatches, never talks to LiveKit directly for voice
make worker   # LiveKit Agents worker — the process that actually joins a room and runs the voice pipeline
cd frontend && npm run dev
```

The API alone can't make an agent talk: it only creates the LiveKit room and dispatches a job to it. Without a worker running to pick that job up, a test call connects to an empty room. Both processes read the same `.env` at the repo root (see `.env.example`) — `backend/.env` is an optional local override layered on top, e.g. for pointing `DATABASE_URL` at `localhost` instead of the Docker Compose service name.

## Cost target

Self-hosted stack lands at **~$0.02–0.06/min all-in** (→ ~$0.01–0.02 once speech models are self-hosted), vs $0.10–0.30/min on managed platforms (Vapi/Retell/Bland). The LLM is <5% of the bill; speech + telephony dominate.

## Roadmap

1. **MVP** — LiveKit Cloud (managed) + Telnyx trunk + one agent worker VM. Agent code is identical to the self-hosted future.
2. **Growth** — autoscaled agent workers; committed-use carrier rates; second carrier.
3. **Scale** — self-host LiveKit server + SIP bridge; self-host STT/TTS/LLM on GPUs.

## Repo layout

- `frontend/` — web dashboard
- `backend/` — API server + LiveKit Agents workers
- `docs/` — research and architecture docs
