# Project Analysis

*What is actually built, what is not, what is distinctive about the project, and where its real limits are — based on direct code inspection (2026-09-02) plus the independent engineering audit in `Kimi_audit.md` (2026-08-19). Where the two sources overlap they are consistent; this document does not repeat the audit's full bug/security list, only what is relevant to understanding the project's technical maturity and direction.*

## 1. What is implemented (working, end-to-end)

| Area | Status | Evidence |
|---|---|---|
| Multi-tenant org/user/auth (register, login, JWT refresh) | Implemented | `routers/auth.py`, `security.py` |
| Agent CRUD with rich per-agent config | Implemented | `schemas/agent.py`, `routers/agents.py` |
| Inbound PSTN calls (Telnyx → LiveKit SIP → agent) | Implemented | `worker/agent.py`, `docs/TELEPHONY_SETUP.md` |
| Outbound PSTN calls, browser test calls | Implemented | `routers/calls.py`, `services/livekit.py` |
| STT: Groq-hosted Whisper, LiveKit streaming gateway | Implemented | `worker/pipeline.py:build_stt` |
| LLM: Groq-hosted Qwen3, configurable model id + temperature | Implemented | `worker/pipeline.py:build_llm` |
| TTS: Groq (Orpheus), Fish Audio (streaming), self-hosted Chatterbox | Implemented | `worker/pipeline.py:build_tts`, `worker/chatterbox_tts.py` |
| Per-agent barge-in/interruption tuning + adaptive backchannel detection | Implemented | `app/interruption.py`, `worker/interruption.py` |
| Function-calling tools: end_call, transfer_call, send_dtmf, generic webhook | Implemented | `worker/tools.py` |
| Knowledge-base retrieval (RAG), org-scoped | Implemented (basic) | `services/knowledge.py`, see §3 |
| Call transcripts, recordings, post-call LLM analysis (custom schema) | Implemented | `models/call.py`, `routers/internal.py` |
| Analytics (call volume, minutes, answer rate, latency percentiles) | Implemented | `routers/analytics.py` |
| Outbound webhooks (HMAC-signed) | Implemented, non-durable (single attempt, in-process) | `services/webhook_dispatch.py` |
| Dashboard covering all of the above | Implemented | `frontend/src/app/(dashboard)/*` |
| Ambience/background audio during calls | Implemented | `models/ambience_clip.py` |
| Test suite for core call/auth/tool logic | Implemented (~3.2k lines, backend only) | `backend/tests/` |

This is a materially working voice-agent platform, not a prototype — a caller can genuinely ring a real number and hold a conversation with an LLM-backed agent that can look things up, transfer the call, or hang up, and the operator can see the transcript and cost afterward.

## 2. What is incomplete or missing

**Documented-but-unbuilt:**
- **Self-hosted STT** (`STT_PROVIDER=local`, the Phase 6 faster-whisper service from `docs/PLAN.md`) — a bare `NotImplementedError`. No service, adapter, or dependency exists.
- Managed phone-number provisioning (Telnyx purchase API) — numbers are added by pasting IDs copied from the Telnyx dashboard.

**Never planned but relevant to any "smarter agent" direction:**
- **No LLM personalization or fine-tuning of any kind.** Every organization's agent is the same shared Groq-hosted `qwen/qwen3.6-27b` model. The only per-business differentiation is (a) free-text system-prompt content the org writes themselves, (b) temperature, and (c) which tools/knowledge are switched on. There is no mechanism for the model to learn a business's phrasing, policies, or recurring intents from its own call history — that history (`call_events`) is stored and displayed but never fed back into anything model-side.
- **No TTS personalization beyond voice-id selection.** No prosody, pacing, pause, emphasis, or emotion control exists in any TTS request payload. No business can shape *how* their agent sounds beyond picking one of a fixed set of stock voices per provider (or, entirely outside the product, cloning a voice through the third-party Chatterbox server's own admin UI).
- **Knowledge base is organization-wide, not per-agent**, uses no ANN index, and is retrieved by an LLM tool call rather than being ranked/injected proactively — fine at the current low chunk-count assumption the code documents, but a real ceiling if knowledge bases grow.

**Product/engineering gaps identified by the independent audit** (`Kimi_audit.md`) worth knowing about because they affect how much new surface area an FYP extension should responsibly add:
- A data-integrity bug where pipeline failures are recorded as successful completed calls (`worker/agent.py`).
- An unfinished auth lifecycle (no logout, revocation, or password reset; tokens in `localStorage`; RBAC defined in the schema but enforced on only a couple of routers).
- No production logging/observability configuration — INFO-level logs, including the per-turn latency telemetry the system already computes, are silently dropped.
- No durable delivery for webhooks or post-call analysis (in-process, single-attempt).

None of these block an FYP extension focused on the AI pipeline, but they are worth naming so a proposal doesn't imply the platform is more hardened than it is.

## 3. Important and distinctive concepts already in the project

These are the parts of the current system worth building on rather than replacing:

1. **A genuinely stateless worker.** The voice-pipeline process holds no database connection and no in-memory session state beyond the active call — it fetches config and reports events over HTTP. This is what makes it credible to later scale to many concurrent calls, and it is the right foundation for adding a fine-tuning or style-serving step (the worker would just fetch one more config field).
2. **Provider abstraction across STT/LLM/TTS.** All three are selected by config/env rather than hardcoded, and the code already tolerates heterogeneous capabilities (e.g., streaming vs non-streaming TTS changes which system-prompt preamble is used). A new "fine-tuned" or "personalized" model/voice is a natural extension of an existing seam, not a new architecture.
3. **A working (if basic) retrieval pipeline already exists.** `services/knowledge.py` is a legitimate, if simple, RAG implementation — multilingual embeddings, chunking, cosine retrieval, LLM tool integration. This means an FYP does not need to build RAG from zero; it needs to extend an existing, real system and compare it fairly against a new fine-tuning-based alternative.
4. **`call_events` is a complete, structured conversation log already being collected.** Every transcript turn, tool call, and status change is stored per call, per organization, per agent. This is precisely the raw material a conversation-based fine-tuning pipeline needs — it does not have to be invented, only cleaned and converted.
5. **Native bilingual (English/Arabic) design throughout**, including RTL-aware UI, Arabic-specific STT/TTS model choices, and language-agnostic chunking — a real differentiator among both open-source and commercial competitors, and a natural axis to demonstrate a fine-tuning/style approach on (style and terminology genuinely differ by language and dialect, giving a fine-tuning-vs-RAG comparison something substantive to measure).
6. **Cost-transparency as a design principle**, not just a slogan — the stack is chosen and documented (`docs/RESEARCH.md`) explicitly against a $/min target, and every call stores a `cost_estimate`. Any new component proposed (fine-tuning inference, extra TTS processing) should be justified against this same lens.

## 4. Main limitations, summarized

- **The "AI" in the product is currently a single shared foundation model plus a system-prompt string.** There is no learning from a business's own data beyond what an operator manually types into a prompt box, and no way for the agent's voice delivery to differ from picking a name off a list. This is the central gap an FYP focused on personalization would address.
- **RAG is a first pass, not a scaled system**: no per-agent knowledge, no vector index, brute-force search over an unbounded-in-theory chunk set.
- **The platform's reliability/observability/auth layers are unfinished** (see `Kimi_audit.md` for the full list), which matters for scoping: a research-focused FYP should treat the existing platform as infrastructure to build a controlled experiment on top of, not assume it is production-hardened.
- **No fine-tuning infrastructure of any kind exists** — no training data export, no adapter storage, no serving path for a customized model, no evaluation harness comparing approaches. This is greenfield.
- **No TTS style/prosody/emotion layer exists** — greenfield in the same way.

These two greenfield areas — conversation-driven LLM personalization and business-specific voice delivery — are exactly where the codebase currently offers a real seam (provider abstraction, stored transcripts, per-agent config) to extend without a rewrite, which is why they are viable FYP directions rather than a wish list.
