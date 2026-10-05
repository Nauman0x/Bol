# BOL — Implementation Plan

> **For the executing model:** Work through phases in order. Each phase ends with acceptance criteria — verify them before moving on. Do not substitute stack choices without asking; the stack was chosen deliberately (see [RESEARCH.md](RESEARCH.md)). Where a secret/account is needed (Groq key, LiveKit, Telnyx), stub with env vars and tell the user exactly what to create — never hardcode or invent credentials.

## Stack (decided — do not change)

- **Backend API**: Python 3.12, FastAPI, SQLAlchemy 2 (async) + Alembic, PostgreSQL, Pydantic v2
- **Agent runtime**: `livekit-agents` (Python) with plugins: `livekit-plugins-groq` (LLM), `livekit-plugins-silero` (VAD), custom/local STT (faster-whisper) and TTS (Chatterbox) — MVP may start with Groq-hosted Whisper STT to get running, then swap to self-hosted
- **LLM**: Qwen3-32B via Groq API (OpenAI-compatible); model name configurable via env
- **Telephony**: LiveKit Cloud (MVP) + Telnyx Elastic SIP trunk; self-hosted LiveKit later — agent code must not assume Cloud
- **Frontend**: Next.js 15 (App Router) + TypeScript + Tailwind + shadcn/ui, TanStack Query
- **Auth**: JWT (access+refresh) issued by our own backend; bcrypt password hashing. No third-party auth service.
- **Infra**: docker-compose for local dev (postgres, redis, api, worker, frontend)

## Monorepo layout (target)

```
BOL/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── pyproject.toml            # uv or poetry; ruff + pytest configured
│   ├── alembic/                  # migrations
│   ├── app/
│   │   ├── main.py               # FastAPI app factory, CORS, routers
│   │   ├── config.py             # pydantic-settings, all env vars
│   │   ├── db.py                 # async engine/session
│   │   ├── models/               # SQLAlchemy models (one file per aggregate)
│   │   ├── schemas/              # Pydantic request/response models
│   │   ├── routers/              # auth, agents, calls, numbers, analytics, webhooks
│   │   ├── services/             # business logic (call dispatch, livekit, telnyx)
│   │   └── security.py           # JWT, password hashing, deps
│   ├── worker/
│   │   ├── agent.py              # LiveKit Agents entrypoint (the voice agent)
│   │   ├── pipeline.py           # STT/LLM/TTS assembly per agent config
│   │   ├── tools.py              # function-tools (transfer, hangup, webhook tools)
│   │   └── stt_tts/              # local faster-whisper + chatterbox adapters (phase 6)
│   └── tests/
└── frontend/
    ├── package.json
    └── src/
        ├── app/                  # (auth)/login, (dashboard)/agents, /calls, /numbers, /analytics, /settings
        ├── components/           # shadcn/ui + custom
        └── lib/                  # api client, auth context, types
```

---

## Phase 0 — Repo scaffolding & dev environment

1. Backend: init `pyproject.toml` (fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, alembic, pydantic-settings, python-jose, bcrypt/passlib, httpx, livekit-agents, livekit-api, ruff, pytest, pytest-asyncio).
2. Frontend: `npx create-next-app@latest` (TS, Tailwind, App Router, src dir) + shadcn/ui init + TanStack Query provider.
3. `docker-compose.yml`: postgres:16, redis:7, api (uvicorn --reload), worker, frontend (dev). Volumes for hot reload.
4. `.env.example` documenting every var (see Env Vars section at bottom).
5. `Makefile` or task runner: `make dev`, `make migrate`, `make test`, `make lint`.

**Accept:** `docker compose up` starts postgres+redis+api+frontend; `GET /health` returns `{"status":"ok"}`; frontend renders a placeholder page; `make test` passes an empty suite.

## Phase 1 — Database schema & auth

SQLAlchemy models + Alembic migration:

- `organizations` — id (uuid pk), name, created_at
- `users` — id, org_id fk, email (unique), password_hash, name, role (`owner|admin|member`), created_at
- `agents` — id, org_id, name, **config jsonb**: `{ system_prompt, greeting, greeting_mode, language ("en"|"ar"|"auto"), voice_id, tts_provider, llm_model, temperature, max_call_duration_sec, interruption_enabled, interruption_style, interruption_mode, interruption_min_duration, interruption_min_words, false_interruption_timeout, ack_on_interrupt, resume_style, filler_phrases, boosted_keywords, ambience, ambience_volume, thinking_sound, analysis_schema }` (see `app/schemas/agent.py:AgentConfig` and `app/interruption.py` for the interruption fields), `tools jsonb` (array of tool defs, see Phase 4), is_active, created_at, updated_at
- `phone_numbers` — id, org_id, e164 (unique), provider (`telnyx`), livekit_trunk_id, inbound_agent_id fk nullable, created_at
- `calls` — id, org_id, agent_id, phone_number_id nullable, direction (`inbound|outbound`), to_number, from_number, status (`queued|ringing|in_progress|completed|failed|no_answer|busy`), livekit_room_name, started_at, answered_at, ended_at, duration_sec, end_reason, recording_url nullable, cost_estimate numeric nullable
- `call_events` — id, call_id fk, ts, type (`transcript_user|transcript_agent|tool_call|tool_result|status|error`), payload jsonb  ← the transcript IS this table
- `api_keys` — id, org_id, name, key_hash, prefix (first 8 chars, shown in UI), created_at, last_used_at

Auth endpoints: `POST /auth/register` (creates org + owner user), `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`. JWT access (15min) + refresh (30d). FastAPI dependency `get_current_user` and `require_org`. All non-auth routes scoped by org — every query filters `org_id`; write a test proving cross-org access is blocked.

**Accept:** register→login→me flow passes in pytest; Alembic migration applies cleanly to a fresh DB; cross-tenant isolation test passes.

## Phase 2 — Agents & numbers CRUD API

- `GET/POST /agents`, `GET/PATCH/DELETE /agents/{id}` — validate config with Pydantic (bounded temperature, prompt length, enum language/voice).
- `GET/POST /phone_numbers`, `PATCH /phone_numbers/{id}` (assign `inbound_agent_id`), `DELETE`. For MVP the number row is created manually after the user buys the DID in the Telnyx portal — document this; a Telnyx purchase API integration is a later stretch goal.
- `GET /voices` — static catalog for now: list of Chatterbox/Groq voice ids with labels and language tags.
- Seed script `backend/scripts/seed.py`: demo org, user (`demo@BOL.dev` / printed password), one agent ("BOL Receptionist", bilingual EN/AR prompt).

**Accept:** full CRUD via pytest + OpenAPI docs render at `/docs`; seed script idempotent.

## Phase 3 — The voice agent worker (core of the product)

`backend/worker/agent.py` using the **livekit-agents 1.x `AgentSession` API**:

1. Worker registers with LiveKit (`LIVEKIT_URL/API_KEY/API_SECRET`) with `agent_name="BOL-agent"` for explicit dispatch.
2. On job: read job metadata (JSON: `{call_id, agent_id}`) → fetch agent config from the API (internal endpoint with service token, `GET /internal/agents/{id}`) — the worker must NOT open its own DB connection; it talks to the API only.
3. Build pipeline per config (`pipeline.py`):
   - VAD: Silero (`livekit-plugins-silero`)
   - STT: MVP = Groq hosted `whisper-large-v3-turbo` via `livekit-plugins-groq`; behind an interface so Phase 6 swaps in local faster-whisper
   - LLM: Groq chat completions, model from config (default `qwen/qwen3.6-27b`), with the agent's `system_prompt` + guardrail preamble ("You are on a phone call. Keep responses under 3 sentences. Never read out URLs or spell long strings unless asked.")
   - TTS: MVP = any Groq/PlayAI TTS voice available via plugin; Phase 6 swaps in Chatterbox. Interface: `synth_stream(text_stream) -> audio_stream`.
   - Turn detection + interruptions enabled per config.
4. Speak `greeting` on connect. Enforce `max_call_duration_sec` (then polite goodbye + hangup).
5. Event reporting: on every final transcript segment, tool call, and status change, `POST /internal/calls/{id}/events` (batched, fire-and-forget with retry queue). On session end, `POST /internal/calls/{id}/complete` with duration + end_reason.
6. Graceful shutdown: SIGTERM finishes active calls, stops accepting new jobs.

**Accept:** with real LiveKit + Groq creds in `.env`, `python -m worker.agent dev` connects; joining the room from LiveKit's Agents Playground (browser mic) yields a working voice conversation; `call_events` rows appear via the API.

## Phase 4 — Telephony (inbound + outbound) & tools

**Telnyx + LiveKit wiring** (document each step in `docs/TELEPHONY_SETUP.md` as you go; these are user actions in dashboards, not code):
- Telnyx: buy DID, create SIP connection (FQDN, credentials), point to LiveKit SIP URI.
- LiveKit: create inbound trunk + dispatch rule (dispatch to `agent_name="BOL-agent"`, room per call, metadata carrying the number); create outbound trunk with Telnyx credentials.

**Code:**
- `services/livekit.py`: wraps `livekit-api` — create SIP participant (outbound dial), create rooms, generate dispatch metadata.
- Inbound: dispatch rule metadata contains the called DID → worker resolves DID→`phone_numbers.inbound_agent_id` via internal API; creates the `calls` row (`direction=inbound`) on session start.
- Outbound: `POST /calls/outbound` `{agent_id, to_number}` → creates `calls` row (`queued`) → creates room + SIP participant + agent dispatch with `{call_id, agent_id}` metadata → status transitions driven by worker events. Also `POST /calls/{id}/hangup` (deletes room). Basic per-org concurrency cap (env `MAX_CONCURRENT_CALLS`, default 5) enforced at dispatch.
- **Agent tools** (`worker/tools.py`), defined per-agent in `agents.tools` jsonb:
  - Built-ins: `end_call` (LLM can hang up politely), `transfer_call` (SIP REFER / dial human number — config: `{transfer_to}`)
  - Generic **webhook tool**: `{name, description, url, method, params_schema}` → LLM function-call → worker POSTs to customer URL with params, returns JSON to LLM. 10s timeout, response truncated to 2KB. This one primitive covers booking/CRM/lookup use cases without bespoke integrations.
- `GET /calls`, `GET /calls/{id}` (with events/transcript), filters: agent, direction, status, date range, pagination.

**Accept:** real phone → DID → agent answers and converses; `POST /calls/outbound` rings a real phone; transcript + tool calls visible via `GET /calls/{id}`; hangup works from both sides and statuses land correctly.

## Phase 5 — Frontend dashboard

Pages (all behind auth; JWT in httpOnly-style handling via API client + refresh):

1. **Login / Register** — minimal, clean.
2. **Agents list + Agent builder** (`/agents`, `/agents/[id]`) — the flagship screen:
   - Form: name, language (EN/AR/auto — **RTL-aware textarea for Arabic prompts**), system prompt (large editor), greeting, voice picker (from `/voices`), model + temperature, max duration, interruptions toggle
   - Tools editor: add/remove webhook tools with JSON schema editor for params; built-in tools as toggles
   - "Test call" panel: button that either (a) opens a LiveKit browser room to talk to the agent mic-to-agent (preferred — no telephony cost; backend endpoint `POST /agents/{id}/test-session` returns a LiveKit token), or (b) triggers an outbound call to a number you type
3. **Calls** (`/calls`) — table (direction, number, agent, status, duration, time) with filters; detail drawer/page: chat-style transcript from `call_events` (user right, agent left, tool calls as system chips), audio player when recording exists
4. **Phone numbers** (`/numbers`) — list, add-number form (paste E.164 + Telnyx ids per TELEPHONY_SETUP doc), assign inbound agent dropdown
5. **Analytics** (`/analytics`) — cards: total calls, total minutes, answer rate, avg duration; simple bar chart calls/day (last 30d) — one backend endpoint `GET /analytics/summary`, computed with SQL, no extra infra
6. **Settings** (`/settings`) — org name, team members (invite = create user w/ temp password for MVP), API keys (create/reveal-once/revoke)

Design: dark, modern, minimal (shadcn defaults are fine for MVP; product name styled "BOL بول"). Full **RTL support** switchable per user locale is a stretch goal; RTL inside prompt/transcript Arabic text is required (use `dir="auto"` on text containers).

**Accept:** every page functional against the real API; create agent → test call in browser → see transcript in Calls, all through the UI. `npm run build` passes with no type errors.

## Phase 6 — Self-hosted speech (cost reduction)

Two standalone GPU services (separate containers, simple FastAPI + websocket servers), each behind the interface defined in Phase 3:

1. **STT service**: faster-whisper `large-v3-turbo`, int8_float16, VAD-chunked streaming websocket (`/stt/stream` accepting 16kHz PCM frames, emitting partial/final segments). Wire into worker as `BOLSTT` (LiveKit `stt.STT` adapter).
2. **TTS service**: Chatterbox Multilingual v3 streaming (`/tts/stream` accepting text chunks, emitting 24kHz PCM). Wire as `BOLTTS` adapter. Voice catalog moves from static to this service.
3. Env switch: `STT_PROVIDER=groq|local`, `TTS_PROVIDER=groq|local`. docker-compose gets an optional `gpu` profile.

**Accept:** with `*_PROVIDER=local` on a GPU machine, an end-to-end call works with no Groq speech usage (Groq only for LLM); latency measured and logged per stage (STT final→LLM first token→TTS first audio) via call_events `payload.timings`.

## Phase 7 — Production hardening

- Call recording: LiveKit egress → S3-compatible storage (env-configured), `recording_url` on call
- Rate limiting (slowapi/redis) on auth + outbound calls; webhook tool SSRF protection (block private IP ranges)
- Structured logging (structlog) + request ids; Sentry hook optional via env
- `docker-compose.prod.yml` + deploy doc: single VM (API+worker+frontend behind Caddy), managed Postgres; later: self-hosted LiveKit guide
- CI: GitHub Actions — ruff, pytest, tsc, next build

---

## Env vars (`.env.example`)

```
# core
DATABASE_URL=postgresql+asyncpg://BOL:BOL@postgres:5432/BOL
REDIS_URL=redis://redis:6379/0
JWT_SECRET=change-me
INTERNAL_SERVICE_TOKEN=change-me        # worker ↔ API auth
API_BASE_URL=http://api:8000
NEXT_PUBLIC_API_URL=http://localhost:8000
# livekit (user creates at cloud.livekit.io — free tier OK for dev)
LIVEKIT_URL=wss://<project>.livekit.cloud
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
LIVEKIT_SIP_OUTBOUND_TRUNK_ID=
# groq (user creates at console.groq.com)
GROQ_API_KEY=
LLM_MODEL=qwen/qwen3.6-27b
# speech
STT_PROVIDER=groq            # groq | local
TTS_PROVIDER=groq            # groq | local
STT_SERVICE_URL=ws://stt:8020
TTS_SERVICE_URL=ws://tts:8021
# limits
MAX_CONCURRENT_CALLS=5
```

## Execution notes for the implementing model

- **Verify library APIs before writing against them** — `livekit-agents` moves fast; check the installed version's docs/examples (`AgentSession`, plugin names) rather than trusting memory.
- Phases 0–2 and 5 need no external accounts; Phases 3–4 need LiveKit Cloud + Groq (free tiers) and Telnyx (paid, ~$2 to test). Pause and ask the user to create accounts when you reach them.
- Keep the worker stateless (config via API, no DB access) — this is what lets workers autoscale later.
- Write tests as you go for API logic; the voice pipeline is verified manually via Agents Playground / test calls.
- Commit at the end of each phase with a message naming the phase.
