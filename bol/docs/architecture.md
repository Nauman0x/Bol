# Architecture

*Reflects the codebase as of 2026-09-02. Every claim below is verified against source (file:line references given); nothing here is aspirational — planned-but-unbuilt work is explicitly marked as such.*

## 1. What the system is

The project is a multi-tenant, self-hostable platform for building and operating AI voice agents that answer or place real phone calls (PSTN, via a SIP trunk) and browser/WebRTC calls. An organization signs up, creates one or more "agents" (a system prompt + voice + tool configuration), attaches a phone number to an agent, and the agent has live voice conversations with callers — transcribing speech, generating replies with an LLM, and speaking them back — with call recordings, transcripts, analytics, and a small tool/function-calling layer (end call, transfer, DTMF, webhook actions, knowledge-base lookup).

The product's positioning (see `README.md`, `docs/RESEARCH.md`) is "open-source-first": every layer except the PSTN carrier itself is self-hostable open-source software, targeting ~$0.02–0.06/min all-in versus $0.07–0.31/min for managed competitors (Vapi, Retell, Bland), with native Arabic support as a specific differentiator.

## 2. Repo layout

```
project-root/
├── backend/
│   ├── app/            # FastAPI API service
│   │   ├── main.py         # app factory, CORS, router mounting, lifespan (embedding model warmup)
│   │   ├── config.py        # pydantic-settings — all env vars
│   │   ├── db.py             # async SQLAlchemy engine/session
│   │   ├── models/           # SQLAlchemy ORM models (one file per aggregate)
│   │   ├── schemas/          # Pydantic request/response models (incl. AgentConfig)
│   │   ├── routers/          # auth, agents, calls, numbers, tools, knowledge, webhooks,
│   │   │                     #   voices, analytics, team, api_keys, internal (worker-facing)
│   │   ├── services/         # business logic: knowledge (RAG), ssrf_guard, webhook_dispatch,
│   │   │                     #   tts_providers, cache (Redis)
│   │   └── security.py       # JWT issuance/verification, password hashing, auth dependencies
│   ├── worker/          # LiveKit Agents voice-pipeline process
│   │   ├── agent.py          # entrypoint: job handling, greeting, tool wiring, event reporting
│   │   ├── pipeline.py       # builds STT/LLM/TTS/VAD per agent config; prompt construction
│   │   ├── tools.py          # function-tools: end_call, transfer_call, send_dtmf, lookup_knowledge, webhook
│   │   ├── interruption.py   # barge-in preset resolution
│   │   ├── chatterbox_tts.py # custom LiveKit TTS plugin for self-hosted Chatterbox
│   │   └── api_client.py     # worker → API HTTP client (config fetch, event reporting)
│   ├── alembic/         # DB migrations
│   └── tests/           # pytest suite (~3.2k lines)
├── frontend/            # Next.js dashboard
│   └── src/
│       ├── app/             # (auth) + (dashboard) route groups
│       ├── components/      # shadcn-style UI on Base UI primitives
│       └── lib/             # api.ts, hooks.ts (TanStack Query), types.ts, auth-context.tsx
├── deploy/chatterbox/   # self-hosted GPU TTS service (Docker, wraps Chatterbox-TTS-Server)
├── docker-compose.yml   # postgres, redis, api, worker, frontend for local dev
└── docs/                # this folder
```

The API and the worker are **separate processes that never share a database connection**. The worker is deliberately stateless: it reads agent config and reports call events over HTTP to `/internal/*` endpoints authenticated with a shared service token, which is what lets worker instances autoscale horizontally without any shared state beyond LiveKit itself.

## 3. High-level architecture

```
                                   ┌────────────────────────────┐
  PSTN caller ──▶ Telnyx SIP ──▶  │  LiveKit server (SFU)       │ ◀── Browser (WebRTC test call)
                  trunk           │  + livekit/sip bridge       │
                                   └──────────────┬─────────────┘
                                                  │ agent joins room as a participant
                                                  ▼
                                   ┌────────────────────────────┐
                                   │  Worker process (Python)    │
                                   │  livekit-agents AgentSession│
                                   │                              │
                                   │  VAD (Silero) → STT → LLM →  │
                                   │  TTS, with turn-detection    │
                                   │  and per-agent barge-in      │
                                   └───────┬─────────────┬───────┘
                                           │ HTTP         │ HTTP (tool call)
                                           ▼             ▼
                          ┌───────────────────────┐  ┌─────────────────────────┐
                          │ FastAPI API service    │  │ Groq / Fish Audio /      │
                          │ /internal/* endpoints  │  │ self-hosted Chatterbox   │
                          │ (config fetch, events, │  │ (LLM, STT, TTS providers)│
                          │  knowledge search)     │  └─────────────────────────┘
                          └──────────┬────────────┘
                                     ▼
                          ┌───────────────────────┐
                          │ PostgreSQL + Redis     │
                          └───────────────────────┘
```

The API **never talks to LiveKit for voice** — it only creates rooms and dispatches jobs. The worker is the only process that actually joins a room and streams audio. This split is why both `make dev` (API) and `make worker` must run for a call to work at all — the API alone connects a caller to an empty room.

## 4. Call lifecycle

### 4.1 Outbound call

1. `POST /calls/outbound {agent_id, to_number}` (`routers/calls.py`) — checks per-org concurrency cap (`MAX_CONCURRENT_CALLS`, advisory-lock serialized), creates a `calls` row (`status=queued`), creates a LiveKit room, creates a SIP participant via `services/livekit.py` (wraps `livekit-api`), and dispatches an agent job with `{call_id, agent_id}` as job metadata.
2. The worker's registered entrypoint picks up the job, fetches the agent's config from `GET /internal/agents/{id}` (service-token authenticated — the worker holds no DB credentials), and builds the voice pipeline (§5).
3. Call status transitions (`ringing` → `in_progress` → `completed|failed|no_answer|busy`) are driven entirely by worker-reported events to `/internal/calls/{id}/*`, not by the API polling LiveKit.
4. On session end the worker posts `/internal/calls/{id}/complete` with duration, `end_reason`, and latency/interruption stats; on every final transcript segment, tool call, and status change it posts (batched, with retry) to `/internal/calls/{id}/events` — these rows are the transcript itself.

### 4.2 Inbound call

A LiveKit dispatch rule (configured against the Telnyx trunk, documented in `docs/TELEPHONY_SETUP.md`) routes an inbound SIP call into a room carrying the called DID in its metadata; the worker resolves DID → `phone_numbers.inbound_agent_id` via an internal API call and creates the `calls` row itself (`direction=inbound`) once the session starts.

### 4.3 Browser test call

`POST /agents/{id}/test-session` returns a LiveKit access token for a browser client to join a room directly — no telephony involved, no carrier cost — which is the intended default way to iterate on an agent during development.

## 5. The voice pipeline (`backend/worker/pipeline.py`, `agent.py`)

For every call, the worker assembles four building blocks per the agent's stored config:

- **VAD**: Silero (`livekit-plugins-silero`), used for both endpointing and barge-in detection.
- **STT** (`build_stt`): selected by the `STT_PROVIDER` env var (not per-agent):
  - `groq` (default) — Groq-hosted `whisper-large-v3-turbo`. Non-streaming; livekit-agents buffers the full utterance and uploads it only after VAD says the caller stopped, adding a measured ~360ms per turn.
  - `livekit` — LiveKit's own streaming inference gateway (`deepgram/flux-general-en` for English, `assemblyai/universal-streaming-multilingual` otherwise). True streaming, and on LiveKit's own network edge rather than Groq's US datacenters — the LATENCY.md investigation found this removes both the serialized buffering delay and ~200ms of RTT.
  - `local` — **a raised `NotImplementedError`.** This is the Phase 6 self-hosted faster-whisper path described in `docs/PLAN.md`; no such service, adapter, or dependency exists in the repo today.
- **LLM** (`build_llm`) — always `groq.LLM` (`livekit-plugins-groq`) against a single hosted endpoint. Per-agent configurable: `model` (string, default `qwen/qwen3.6-27b`) and `temperature` (0.0–2.0, default 0.7). `reasoning_effort="none"` is hardcoded platform-wide as a workaround (the Groq plugin's own model allowlist for auto-disabling reasoning only recognizes the older model id, so without this override every reply is preceded by a full hidden `<think>` block). No other sampling parameters (top_p, max_tokens, penalties) are exposed.
- **TTS** (`build_tts`) — one of three providers selected by `config.tts_provider`:
  - `groq` — Groq's Orpheus TTS, non-streaming, voice/model pairs hardcoded (6 English voices → `canopylabs/orpheus-v1-english`, 4 Arabic voices → `canopylabs/orpheus-arabic-saudi`).
  - `fish` — Fish Audio, real WebSocket streaming; voice catalog fetched live from Fish's API and cached in Redis.
  - `chatterbox` — self-hosted (`deploy/chatterbox/`, GPU container wrapping the open-source Chatterbox-TTS-Server), reached through a custom LiveKit plugin (`worker/chatterbox_tts.py`) that calls its native per-sentence streaming endpoint for lower time-to-first-byte.

  In every case, TTS is invoked as *fixed-`voice_id` text-to-speech*: the payload sent to each provider carries only text (and, for Chatterbox, `language`) — there is no prosody, emotion, speaking-rate, or style parameter anywhere in these request payloads. Voice selection is picking a `voice_id` string from a static per-provider catalog (`routers/voices.py`); there is no product-side voice upload or cloning flow (Chatterbox-TTS-Server does support zero-shot cloning, but only via its own separate admin UI/API, entirely outside the product's own dashboard or data model).

- **System prompt** (`build_instructions`) — a single hardcoded guardrail preamble (choosing between a streaming-TTS and non-streaming-TTS variant, the latter asking the model to open with a short acknowledgment phrase to mask buffered-TTS latency) is string-concatenated in front of the org's own `config.system_prompt` text. There is no template engine, no variable substitution, and no retrieved knowledge injected here — knowledge only enters mid-call via a tool call (§6).
- **Turn detection / barge-in** (`app/interruption.py`, `worker/interruption.py`) — a per-agent preset (`instant`/`balanced`/`patient`/`custom`) resolves to VAD silence-duration and false-interruption-timeout thresholds. An `adaptive` mode additionally runs an ML backchannel classifier (distinguishing "mhm" from a real interruption) but requires the `livekit` streaming STT path — on the Groq STT fallback it silently downgrades to plain VAD and reports an `adaptive_interruption_unavailable` status event.

## 6. Knowledge base (retrieval)

A minimal but real retrieval pipeline, organization-scoped (not per-agent):

1. **Ingest** (`routers/knowledge.py`, `services/knowledge.py`) — uploaded document text is split into fixed 800-character chunks with 100-character overlap (a deliberately language-agnostic scheme, chosen to behave the same for Arabic and English rather than relying on sentence/token boundaries).
2. **Embedding** — `fastembed`, model `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-dim, ONNX, CPU, runs in-process in the API container; warmed at API startup). No external embedding API or key is used.
3. **Storage** — `KnowledgeChunk.embedding` is a plain Postgres/SQLite `JSON` column holding a float array. There is no pgvector extension and no ANN index — retrieval is brute-force numpy cosine similarity over every chunk belonging to the org, deliberately, on the stated assumption that per-org chunk counts stay in the tens-to-low-hundreds.
4. **Retrieval trigger** — knowledge is **not** injected into the system prompt at session start. It is exposed to the LLM as an on-demand function tool, `lookup_knowledge`, described to the model as something to call "whenever the caller asks something that might be covered by uploaded documents." When called, the worker POSTs the query to `/internal/knowledge/search`, which returns the top-4 chunks above a 0.3 cosine-similarity floor, joined into one text blob that becomes the tool's return value — which the LLM then works into its next reply.
5. **Scoping** — one knowledge base per organization. An org running multiple agents cannot give them different knowledge; the only per-agent control is whether the `lookup_knowledge` tool is enabled at all.

## 7. Tools / function-calling (`backend/worker/tools.py`)

Per-agent `tools` config (JSON array on the `agents` row) can enable:

- `end_call` — LLM hangs up politely.
- `transfer_call` — SIP `REFER` to a configured human number.
- `send_dtmf` — sends touch-tone digits (e.g., to navigate an IVR), spaced 150ms apart to avoid carrier-side merging.
- `lookup_knowledge` — the RAG tool call described above.
- `tool_ref` (first-class custom tools, backed by the `Tool` model) — a generic outbound-webhook tool: name/description/URL/method/params schema/headers (with Fernet-encrypted secret support)/timeout/retry/blocking-vs-fire-and-forget/response-field extraction. This one primitive is how CRM lookups, booking systems, etc. are integrated without bespoke code.
- `webhook` (legacy inline shape) — kept only for backward compatibility with agents configured before `tool_ref` existed.

## 8. Database schema (`backend/app/models/`)

| Table | Key fields | Notes |
|---|---|---|
| `organizations` | name | tenant root |
| `users` | org_id, email (unique), password_hash, role (owner/admin/member) | RBAC roles exist but are enforced on few endpoints |
| `agents` | org_id, name, config (JSON — full `AgentConfig`), tools (JSON), is_active | one row per voice agent |
| `phone_numbers` | org_id, e164 (globally unique), provider, livekit_trunk_id, inbound_agent_id (FK, SET NULL) | numbers are provisioned manually today (no carrier API integration) |
| `calls` | org_id, agent_id, phone_number_id, direction, status, livekit_room_name, timestamps, duration_sec, end_reason, recording_key, cost_estimate, analysis (JSON), latency_stats (JSON) + flattened latency columns | one row per call |
| `call_events` | call_id, ts, type (transcript_user/transcript_agent/tool_call/tool_result/status/error), payload (JSON) | append-only — this **is** the transcript |
| `knowledge_documents` / `knowledge_chunks` | org_id, name / document_id, org_id, text, embedding (JSON float array) | see §6 |
| `webhooks` | org_id, url, secret (HMAC), events (JSON) | outbound event notifications (call.completed, etc.) |
| `tools` | org_id, name (unique per org), url, method, params, headers, secrets_enc, timeout, retry, blocking, response_extract | reusable custom tool definitions |
| `ambience_clips` | org_id, name, content_type, duration_sec, data (raw bytes, ≤5MB/120s, stored directly in Postgres) | background-audio-during-call feature |
| `api_keys` | org_id, name, key_hash, prefix, last_used_at | programmatic access |

## 9. Frontend (`frontend/src/`)

Next.js App Router, all pages client components, TanStack Query for data fetching. Routes: `(auth)/login`, `(auth)/register`; `(dashboard)/agents` (list + builder), `/calls` (list + transcript/latency/analysis detail), `/knowledge`, `/numbers`, `/tools`, `/analytics`, `/settings`. `lib/api.ts` is a thin fetch wrapper handling JWT storage (in `localStorage`) and 401-triggered refresh; `lib/hooks.ts` centralizes every query/mutation; `lib/types.ts` mirrors the backend Pydantic schemas.

## 10. Deployment

Local dev: `docker-compose.yml` (postgres, redis, api, worker, frontend). Production target: Railway, one service each for API/worker/frontend (`railway.*.json`), managed Postgres, plus the standalone `deploy/chatterbox/` GPU container when self-hosting TTS. Both API and worker read the same root `.env`. CI (`.github/workflows/`) runs ruff + pytest (SQLite, `metadata.create_all` — migrations are never exercised against Postgres in CI) and eslint + `next build`.

## 11. What is genuinely load-bearing vs. what is a stub

To avoid the common mistake of describing the roadmap as if it were shipped:

| Claimed in docs/README | Actually implemented? |
|---|---|
| LiveKit + Telnyx PSTN calling | **Yes** — full inbound/outbound flow |
| Groq-hosted Qwen3 LLM | **Yes** |
| Multiple STT/TTS providers | **Yes**, for Groq, Fish Audio, and self-hosted Chatterbox |
| Self-hosted faster-whisper STT (Phase 6) | **No** — `NotImplementedError` stub only |
| Per-agent barge-in tuning, adaptive interruption detection | **Yes** |
| Knowledge-base RAG | **Yes**, but basic: org-wide scope, no ANN index, tool-call triggered rather than prompt-injected |
| LLM fine-tuning / personalization / LoRA / PEFT | **No** — no code anywhere in the repo; every org shares one Groq-hosted model, differentiated only by prompt text |
| Business-specific TTS style / prosody / emotion control | **No** — TTS calls carry text and a fixed `voice_id` only |
| Per-business custom voice cloning inside the product | **No** — cloning capability exists only in the third-party Chatterbox-TTS-Server's own admin surface, outside the product's own dashboard/API |
