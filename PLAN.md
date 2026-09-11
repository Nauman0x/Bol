# Bol — Implementation Plan & Status

Team: Nauman, Khadija, Esha, Muzammil, Ashna. Branches: `dev-nauman`, `dev-khadija`, `dev-esha`, `dev-muzammil`, `dev-ashna`, all cut from `main`.

## Done — skeleton milestone (Phases 0-4)

Committed to `main`:

- **Phase 0 — repo scaffolding**: docker-compose (postgres, redis, api, worker, frontend), Makefile, `.env.example`, backend/frontend Dockerfiles.
- **Phase 1 — DB schema & auth**: SQLAlchemy models + Alembic migration (`organizations`, `users`, `agents`, `calls`, `call_events`); JWT auth (register/login/refresh/me), bcrypt hashing, org-scoped access on every route; pytest covers the auth flow and cross-tenant isolation.
- **Phase 2 — agent CRUD**: full CRUD, static voice catalog, seed script (`demo@bol.dev`).
- **Phase 3 — voice agent worker**: stateless LiveKit worker (`backend/worker/`), config fetched over HTTP from `/internal/*` (no DB access). `AI_PROVIDER=stub` (default, zero AI keys needed) vs `AI_PROVIDER=groq` seam in `pipeline.py`.
- **Phase 4 — frontend dashboard**: Next.js 15 + shadcn/ui + TanStack Query. Login/register, agent builder, live browser test call, calls list + transcript view. `npm run build` passes clean.

Verified against the real Aiven Postgres + LiveKit Cloud project in `.env`: migration applied, seed data present, DB connection confirmed.

**Known follow-up from Phase 3** (flagged when written, not yet run against real installed deps): confirm `AgentSession(stt=None, llm=None, tts=None)` actually constructs in stub mode, and that the `AgentServer`/`@server.rtc_session` API shape used in `backend/worker/agent.py` matches whatever `livekit-agents` version actually resolves once `pip install` is run for real. Do this before relying on Phase 3a in a real test call.

## Left — pick up from here

Not started. Suggested split across 5 people (reassess once you see who's strongest where):

- **Phase 5 — call history polish & minimal analytics**: pagination/filters on `/calls`, one `GET /analytics/summary` query.
- **Phase 6 — knowledge base (RAG)**: `knowledge_documents`/`knowledge_chunks` tables, chunk + embed (multilingual), brute-force cosine retrieval, wired in as an LLM tool call (`lookup_knowledge`), not a system-prompt injection.
- **Phase 7 — LLM personalization / fine-tuning**: export `call_events` → clean/PII-redact → JSONL → QLoRA fine-tune (Qwen2.5-7B or Llama-3.1-8B, not the production Groq model) → eval before shipping. Bigger, research-flavored — good to split across two people.
- **Phase 8 — Voice Style Profile (TTS personalization)**: per-org voice/rate/pause/tone profile, needs a TTS provider with generation-control params (Groq's stock voices don't have this — evaluate self-hosted Chatterbox).
- **Phase 9 — telephony**: LiveKit + SIP trunk (e.g. Telnyx), inbound/outbound real phone calls. Carrier setup is a dashboard action, not code — do it with the account in front of you.
- **Phase 10 — production hardening**: rate limiting, structured logging, error tracking, CI, `docker-compose.prod.yml`, deploy target. Pull earlier if real users show up before Phase 6-9 land.

Full detail for every phase (acceptance criteria, exact schema, env vars) is in the original plan the skeleton was built from — ask Nauman if it's not already in the repo history/chat.

## Ground rules carried over

- Worker stays stateless (config via API, no DB access) — don't retrofit this later, it's expensive.
- Write tests for API logic as you go; the voice pipeline itself is verified by an actual test call, not unit tests.
- Commit at the end of each phase/sub-feature with a message naming it, so the team can track who's where.
- When unsure whether something belongs in the current phase or a later one, defer — small and working beats anticipating features nobody's asked for yet.
