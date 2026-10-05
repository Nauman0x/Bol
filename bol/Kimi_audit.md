# BOL — Product & Competitive Engineering Audit

*Audit date: 2026-08-19. Scope: full codebase (backend, worker, frontend, infra, tests, CI/CD), product flows, security, reliability, UX, features, and competitive position. **This is not an SEO audit** — search-engine topics are excluded per instructions. Method: parallel deep-dive audits over the actual code (backend/security, frontend/UX, infra/reliability, competitor research) plus manual spot-verification of all P0 claims by direct file reads. No code was modified. Builds/tests could not be executed locally (no venv/node_modules on this machine) — findings marked LIKELY need runtime confirmation; everything else is CONFIRMED by reading the code. Competitor facts are cited from vendor pages fetched 2026-08-19; items marked UNVERIFIED could not be externally confirmed.*

---

## 1. Executive Summary

BOL is an open-source, self-hostable AI voice-agent platform: businesses build AI phone agents (inbound receptionist, outbound calls) over LiveKit + Telnyx SIP, with Groq-hosted Qwen3 as the LLM, pluggable STT/TTS (Groq / Fish Audio / self-hosted Chatterbox), and native Arabic+English support. The wedge is real: ~$0.02–0.06/min all-in vs competitors' verified $0.07–0.31/min, true self-hosting, and an Arabic-capable stack no competitor productizes.

The engineering core is above average for an MVP — clean layering, a genuinely stateless worker, thoughtful consistency machinery (advisory locks, terminal-status guards, stale-call reaping), and real tests on the money paths. What undermines it: (1) data-integrity bugs in the API↔worker call-state protocol — failed calls are recorded as successful; (2) a half-built auth lifecycle (no logout, no revocation, no password reset, no member removal, tokens in localStorage) with RBAC defined but unenforced; (3) no observability — INFO logs are silently dropped, no error tracking, no metrics; (4) activation-killing UX friction (blank-prompt agent form, manual carrier-ID pasting).

| Dimension | Score /100 | Rationale |
|---|---|---|
| Product Health | 55 | Core pipeline works; broken seed, wrong call outcomes, high setup friction |
| Code Quality | 72 | Clean layering, honest comments, good tests on money paths; some fragile state handling |
| Architecture | 74 | Stateless worker, shared provider logic, sound DB design; auth/RBAC and durability layers unfinished |
| Security | 55 | Good instincts (SSRF guard, boot-time secret validation) but token storage, revocation, RBAC, SSRF TOCTOU gaps |
| Performance | 62 | Backend lean, indexes match queries; frontend all-client SPA with untuned query layer |
| Reliability | 52 | Good shutdown/reaper design, but non-durable webhooks/analysis, no logging, unreproducible builds |
| UX | 40 | Functional dashboard; no onboarding, worst-step number setup, missing error states, broken mobile nav |
| Test Coverage | 65 | ~3.2k lines covering core call paths; team/api-keys/ambience/seed/SSRF-edge/dispatch untested, no E2E |
| Competitive Position | 42 | Strong wedge (cost/Arabic/self-host); Dograh already owns the OSS-alternative narrative with better onboarding |

- **Biggest technical risk:** the call-state protocol corrupts data silently — pipeline failures complete as `status=completed` with fake durations (`worker/agent.py:251`), and `/internal/calls/{id}/answered` can resurrect terminal calls (`internal.py:156`). Analytics, cost estimates, latency stats, and customer webhooks all inherit these lies.
- **Biggest product weakness:** activation friction. A new user faces a blank 30-control form, then must buy a DID in a carrier dashboard and paste an internal LiveKit trunk ID (`numbers/page.tsx:95-138`) before the product does anything real for them.
- **Biggest competitive weakness:** Dograh (BSD-2, one-command setup, browser voice testing with no API keys, MCP server, PH #1) already delivers the "open-source Vapi/Retell alternative" onboarding BOL aspires to — BOL requires Docker + trunk provisioning + multiple third-party accounts before first value.
- **Biggest opportunity:** Arabic-first productization (dialect-tuned demos, RTL dashboard, GCC carrier recipes, PDPL/self-host deployment story). No competitor — including Twilio's AI layer, which doesn't support Arabic at all — owns this.

---

## 2. Product & System Understanding

**What it does:** multi-tenant SaaS-style platform (self-hostable) for building and operating AI voice agents on real phone lines and browser WebRTC calls.

- **Target users:** developers and SMB operators wanting AI phone agents without per-minute platform tax; Arabic-speaking markets (KSA/UAE) underserved by US-centric tools.
- **User roles:** `owner | admin | member` (`models/user.py`) — defined, but enforced only on team invite and org rename.
- **Primary use cases:** inbound AI receptionist, outbound calls, browser test calls, call transcripts/recordings/analytics, knowledge-base-grounded agents, webhook-tool actions mid-call, post-call AI analysis, ambience audio.
- **Critical journeys:** (a) register → create agent → browser test call → view transcript; (b) buy DID → attach Telnyx/LiveKit trunk → inbound call answered by agent; (c) `POST /calls/outbound` → PSTN ring → conversation → completion + webhook to customer; (d) settings: team invite, API keys, outbound webhooks.

**Stack:**

- **Frontend:** Next.js **16.3.1** (App Router, React 19.2.8), TypeScript, Tailwind, shadcn-style primitives on **Base UI** (not Radix), TanStack Query. All 27 pages are client components.
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2 async + Alembic, PostgreSQL 16, Redis 7 (login rate-limit + voice catalog cache), Pydantic v2.
- **Worker:** `livekit-agents` Python worker — stateless, fetches config and reports events only via `/internal/*` HTTP endpoints with a shared service token.
- **DB:** orgs, users, agents (jsonb config/tools), phone_numbers, calls, call_events (the transcript), api_keys, knowledge docs/chunks, ambience_clips, webhooks. Composite indexes match query patterns (migration `b8e2f1a4c6d0`).
- **Auth:** JWT access (15min) + refresh (30d), bcrypt. Endpoints are exactly `register/login/refresh/me` (verified via grep of `auth.py`) — **no logout, no password reset, no email verification, no MFA**. Team invite = create user with a temp password shown once in the UI. There is **no email/notification system at all** (grep-verified).
- **Integrations:** LiveKit Cloud (SFU + SIP bridge + egress), Telnyx (carrier), Groq (LLM + STT + TTS), Fish Audio (TTS), Chatterbox (self-hosted TTS), S3-compatible storage (recordings, presigned playback).
- **Payments/subscriptions:** none — no billing system exists.
- **Background work:** in-process FastAPI `BackgroundTasks` for post-call analysis + webhook dispatch (single attempt, non-durable); worker-side batched event reporter with retry; lazy stale-call reaper on the API path.
- **AI features:** LLM conversation (function-calling tools: end_call, transfer_call, send_dtmf, generic webhook tool), post-call analysis with customer-defined JSON schema, knowledge-base semantic search (fastembed embeddings baked into the image).
- **Deployment:** Railway (api/worker/frontend services, `railway.*.json`), docker-compose for dev, `deploy/chatterbox/` for GPU TTS. CI: ruff + pytest, eslint + `next build`.
- **Testing:** pytest + SQLite (schema via `metadata.create_all`, migrations never exercised); no frontend tests; no E2E.

---

## 3. Critical P0 Issues

| Issue | Category | Evidence | Impact | Recommended Fix | Effort |
|---|---|---|---|---|---|
| Pipeline failures reported as successful completed calls | Bug / Reliability | `worker/agent.py:251` — `end_reason = "completed"` is the init value; `"pipeline_error"`/`"agent_config_fetch_failed"` exist only in `internal.py:58-59` and a test — the worker never sends them. Any exception after cleanup registration (missing TTS key, `session.start` failure) completes the call normally | Analytics, cost estimates, latency stats, and customer webhooks are corrupted by phantom successful calls — the product's core record-keeping lies | Wrap post-registration body in try/except setting `end_reason="pipeline_error"`; report config-fetch failures before early `ctx.shutdown` | S |
| SSRF DNS-rebinding TOCTOU on webhook tool + outbound webhooks | Security | `services/ssrf_guard.py:29-44` resolves DNS and validates IPs; httpx (`worker/tools.py:36-39`, `webhook_dispatch.py:44-52`) re-resolves at connect time — validated IP ≠ connected IP. Any org member can point an agent webhook tool at an attacker domain that flips to a private/metadata IP | Server-side request forgery from a core product feature (LLM-driven outbound HTTP) — reach internal services/cloud metadata | Resolve once, connect to the validated IP with Host header/TLS SNI pinned; block 100.64.0.0/10 (CGNAT); re-validate after any redirect | S |
| Demo seed broken | Bug / DX | `scripts/seed.py:48` — `password_hash=hash_password(password)` without `await` on an `async def` (verified by direct read) | `make seed` stores a coroutine object and fails — the documented quickstart path breaks at the exact moment an evaluator decides to stay or leave | `await hash_password(password)`; add a seed smoke test | XS |
| Tokens in localStorage + no rotation/revocation/logout | Security | `frontend/src/lib/api.ts:3-24` stores access **and** refresh tokens in localStorage (verified); `auth.py` has no logout (4 endpoints total, grep-verified), no server-side token store, no `is_active` on `User`; no CSP in `next.config.ts` | One XSS (or one compromised dependency — `livekit-client` is large) exfiltrates a 30-day credential that cannot be revoked; an org owner cannot offboard a departed member | httpOnly `SameSite=Lax` cookie for refresh token; server-side token store with rotation + reuse detection; logout endpoint; `is_active`; CSP headers | M |
| Members mint API keys that authenticate as org owner | Security / Authz | `routers/api_keys.py:27-51` has no role check; `security.py:89-100` authenticates every API key as the org **owner** (first by `created_at`) | Privilege escalation inside every org; RBAC exists in the schema but is enforced on only two endpoints | Restrict key creation to owner/admin; scope keys to creator's role; write and enforce a permission matrix | M |
| Non-reproducible builds + migrations never tested in CI | Reliability / DX | `backend/pyproject.toml` — all deps `>=`, no lockfile; `Dockerfile:21,30` and `ci.yml` resolve fresh each build; tests use `metadata.create_all` on SQLite (`conftest.py:40-41`), `alembic upgrade head` never runs; no Docker build job | CI tests one dependency set, the deploy builds another; a bad upstream release or broken migration ships green and takes the API down at container start | `uv lock` used by Dockerfile + CI; CI job with Postgres service: `alembic upgrade head` + drift check; docker-build smoke job for all 3 images | S |

---

## 4. High-Priority P1 Issues

**Backend / bugs**
- `internal.py:140-158` — `mark_call_answered` sets `status=in_progress` unconditionally (verified); a late/retried call racing `/complete` resurrects terminal calls and corrupts history. Guard against `_TERMINAL_STATUSES` like the sibling `complete_call` does. *(Confirmed, XS)*
- `calls.py:113-114,222-235` — `_reap_stale_calls` commits mid-request, releasing the transaction-scoped advisory lock that serializes the concurrency-cap check — reopens the exact race the lock was added for. *(Confirmed, S)*
- Unhandled `IntegrityError` → 500s: cross-org duplicate `e164` (globally unique, checked only within org — `numbers.py:55-61`); deleting a number with call history (`numbers.py:96-104`); oversized ambience filename into `String(200)` (`ambience.py:97`). *(Confirmed, S)*
- Path traversal: `ambience="custom:../../..."` flows verbatim into `worker/ambience.py:44` as a cache path and is played into call audio if the file exists. Validate `clip_id` as UUID. *(Confirmed; requires org membership — bounded blast radius, XS)*
- Rate limiting exists only on login; API-key auth costs ~50–100ms bcrypt per request unthrottled; knowledge embedding is CPU-heavy and unthrottled; `POST /calls/outbound` spends real carrier money with a concurrency cap but no rate cap. *(Confirmed, S)*

**Frontend**
- No global session-expiry handling: failed refresh clears tokens but `AuthContext.user` stays set — zombie dashboard with 401-toast storms; logout never clears the TanStack cache, so the next login on a shared machine sees the previous org's data (`api.ts:43`, `auth-context.tsx:68-71`). *(Confirmed, S)*
- Concurrent-401 refresh race: no in-flight dedup on `refreshAccessToken` (`api.ts:79-84`); with 5s polling, two 401s both consume the rotated refresh token → forced logout mid-session. *(Likely — depends on backend single-use semantics, S)*
- Mobile nav overflows: logo + 6 links + email + sign-out in one non-wrapping row (`(dashboard)/layout.tsx:41-76`) — clipped at ≤430px, no hamburger. *(Confirmed, S)*
- `agent-form.tsx:685-693` — `key={i}` on webhook-tool editors + array splice = state corruption: removing a tool leaves the next editor holding the removed tool's JSON schema text. *(Confirmed, S)*
- Invalid JSON in tool/analysis textareas is silently discarded on save while the toast says "Agent saved" (`agent-form.tsx:183-193,712-722`). *(Confirmed, S)*
- No error states anywhere — a 500 on `/agents` renders as the empty state; "Agent not found" shown on network errors; no `error.tsx`/`not-found.tsx`. *(Confirmed, S)*

**Infra / reliability**
- No logging configuration anywhere in app/worker code — INFO logs (including per-turn latency telemetry, `agent.py:407`) are silently dropped on the API; no request IDs, no JSON logs, no Sentry. Production voice incidents are currently undebuggable. *(Confirmed, S)*
- Webhook delivery + post-call analysis are single-attempt, in-process, non-durable (`internal.py:278`, `webhook_dispatch.py:26-29`) — every deploy and every transient receiver failure silently drops customer `call.completed` events. *(Confirmed, M)*
- `deploy/chatterbox/docker-compose.yml:26` mounts `./config.yaml`, which does not exist in the repo — self-hosted TTS breaks on first `up` (Docker creates an empty directory). *(Confirmed via `git ls-files`, XS)*
- `Makefile` uses `. .venv/bin/activate` — nonexistent on the maintainer's Windows machine; every backend target fails outside WSL. *(Confirmed, XS)*

---

## 5. P2/P3 Issues

- Auth lifecycle: no password reset, no email verification, no MFA (endpoints grep-verified: only register/login/refresh/me); emails not lowercased at register/login (`auth.py:41,77` — case-duplicate accounts); bcrypt 72-byte truncation vs `max_length=128` (`schemas/auth.py:12`); user enumeration via 409 + bcrypt timing short-circuit (`auth.py:41-43,79`). *(P2, confirmed)*
- `/internal/*` mounted on the public app with only a shared token — no IP allowlist/defense in depth (`main.py:114`). `/health/config` unauthenticated, discloses integration inventory (`main.py:70-84`). *(P2)*
- Call-event retry duplicates transcripts (no idempotency key, `worker/api_client.py:80-117`); answer-wait listener registered after the status check — a flip in between yields a false `no_answer` after 45s (`agent.py:163-181`); inbound calls bypass all concurrency caps (undocumented, `internal.py:89-126`). *(P2, confirmed)*
- Webhook payload inconsistency: `cost_estimate` serialized as string via `default=str` while `duration_sec` is numeric; no timestamp/delivery-id in the HMAC → receivers can't reject replays. *(P2/P3)*
- Broken migration downgrade (`cbbb8ddee9b7` drops an unnamed constraint); enum value `'test'` has no downgrade path. *(P3)*
- Frontend: LLM model is a free-text input — a typo bricks the agent (`agent-form.tsx:437-441`); `Number("") === 0` silently zeroes `temperature`/`max_call_duration_sec` (`:452,463,592`); `formatMs` takes seconds in one file and ms in another (`calls/[id]/page.tsx:42` vs `analytics/page.tsx:19`); dead code (`dialog.tsx`, `dropdown-menu.tsx`, `tabs.tsx`, unwired `next-themes`, unreachable `.dark` theme block); settings forms allow double-submit; unmemoized auth context value; `<html lang="en">` hardcoded, no `dir`; brand "بول" forced into a latin-only Geist subset; team invite hardcodes role `"member"` with no picker and no removal; `last_used_at` collected on API keys but never displayed. *(P2/P3, confirmed)*
- Infra: containers run as root; GitHub Actions tag-pinned not SHA-pinned; no pip cache/`timeout-minutes`/`concurrency` in CI; no dependency vuln scanning; `/health` doesn't check the DB; DEPLOYMENT.md omits the region guidance LATENCY.md calls "a deployment requirement"; seed prints the demo password into container logs; `backend/.env.example`'s `dev-secret-change-me` passes the boot-time secret validator; no prod-like local compose. *(P2/P3, confirmed)*

---

## 6. Bugs & Broken Functionality (user-journey order)

1. `make seed` fails (P0) — quickstart broken.
2. Register → empty-state card with **no CTA inside it** (`agents/page.tsx:48-54`).
3. Agent form: index-key tool corruption; silent JSON discard with success toast; free-text model name; `Number("")` zeroing; no unsaved-changes guard.
4. Concurrent 401s → random forced logout; expired session → zombie dashboard; logout → next user on the same browser sees your cached data.
5. Delete a number with call history → 500; duplicate number across orgs → 500; long ambience filename → 500.
6. Failed calls (missing TTS key, worker error) appear in the dashboard, analytics, and customer webhooks as **successful completed calls** (P0).
7. Late `/answered` event flips a completed call back to `in_progress`, where it sits until the reaper marks it `worker_lost`.
8. Mobile: header clips; Save button 700px down a flat form; test panel below the fold.
9. Chatterbox self-host: `config.yaml` mount breaks first boot.
10. Webhook tool with a bad URL is only discovered mid-call (no save-time validation, `schemas/agent.py:20`).

Dead/placeholder logic: 3 unused UI primitives; `next-themes` imported but never mounted; agent filter in `useCalls` never exposed in UI; `last_used_at` never displayed; `docs/TELEPHONY_SETUP.md` referenced as unlinked prose in production UI; `transfer_call` is genuinely implemented (LiveKit `transfer_sip_participant`, `agent.py:345`) — not a stub.

---

## 7. Security Findings

| Severity | Finding | Affected Code | Attack Surface | Impact | Defensive Fix |
|---|---|---|---|---|---|
| **Critical** | Refresh+access tokens in localStorage; no rotation/revocation/logout; no CSP | `api.ts:3-24`, `auth.py:89-109`, `next.config.ts` | Any XSS or compromised dependency exfiltrates a 30-day credential | Full account takeover with no remediation path | httpOnly SameSite cookie; server-side token store w/ rotation + reuse detection; logout; CSP |
| **High** | SSRF DNS-rebinding TOCTOU | `ssrf_guard.py:29-44`, `worker/tools.py:36`, `webhook_dispatch.py:44` | Org member configures agent webhook tool / outbound webhook URL | Reach internal services, cloud metadata (169.254.x is blocked, rebinding bypasses) | Pin connection to validated IP (Host/SNI preserved); block 100.64.0.0/10; re-check redirects |
| **High** | API keys authenticate as org owner regardless of creator role | `api_keys.py:27-51`, `security.py:89-100` | Any `member`-role user | Privilege escalation to owner for every org | Role-check creation; scope keys to creator; enforce permission matrix |
| **High** | Path traversal via ambience clip id | `worker/ambience.py:30,44-46`, `schemas/agent.py:65` | Org member sets `ambience: custom:../../...` | Worker-local files played into live calls and recordings | Validate `clip_id` as UUID in worker + schema validator |
| **Medium** | No refresh revocation / user deactivation / member removal / password reset | `auth.py`, `models/user.py`, `team.py` | Stolen token valid 30d; departed members keep access; locked-out users have no recovery | Persistent unauthorized access | Token family store, `is_active`, removal/reset endpoints |
| **Medium** | Rate limiting only on login | `cache.py`, `security.py:71-101`, `routers/knowledge.py:36-58` | Unauthenticated bcrypt-costly API-key auth; CPU-heavy embedding; authed money-spending endpoints | DoS / cost amplification | Redis sliding-window limits on register/refresh/api-key/outbound/test-session/knowledge |
| **Medium** | `/internal/*` god-token endpoints on the public app | `main.py:114` | Anyone who obtains the shared service token gains cross-org access to agents, knowledge, call control | Full cross-tenant compromise | Separate port/ingress rule/IP allowlist |
| **Medium** | User enumeration; case-sensitive emails; bcrypt 72B truncation | `auth.py:41-79`, `schemas/auth.py:12` | Anonymous probing; case-variant duplicate accounts | Account discovery; auth bypass edge cases | Dummy verify on unknown user; normalize email; cap 72B or pre-hash |
| **Low** | Webhook payloads lack timestamp/delivery-id (replay); no retry/delivery log | `webhook_dispatch.py` | Captured payloads replayable against receivers | Receiver-side confusion; missed deliveries | `X-BOL-Timestamp` + delivery id; document tolerance checks |
| **Low** | `/health/config` discloses integration inventory; demo password in container logs | `main.py:70-84`, `seed.py:53` | Recon; log readers | Information disclosure | Auth-gate or trim; warn in seed output |

**Positive findings:** JWT algorithm pinned and token-type checked; `secrets.compare_digest` on internal auth; boot refuses default secrets (outside pytest); all SQL parameterized (single `text()` use is a parameterized advisory lock); no PII/hash leakage in any response schema (verified); `recording_key` excluded from serialization; S3 playback presigned on demand, never stored; ambience uploads re-sniffed server-side via mutagen; SSRF re-validated at delivery time, not just at subscription; webhook HMAC secrets generated per-webhook and shown once.

**Must fix before real users:** rows 1–6.

---

## 8. Architecture & Code Quality Findings

**What's genuinely good (don't touch):** clean routers/services/models/schemas layering; a stateless worker that only talks HTTP to `/internal/*` (this is what lets workers autoscale); shared provider-resolution logic between API and worker (`app/tts_providers.py` — no logic drift); consistency machinery (advisory-lock serialization, terminal-status first-write-wins, lazy stale-call reaping, orphaned-room cleanup on dispatch failure); honest comments documenting verified-vs-assumed behavior; frontend `lib/` layering with every mutation invalidating the right query keys (verified across `hooks.ts` — zero missing invalidations).

**Weaknesses (systemic, not stylistic):**

1. **The auth subsystem was under-designed relative to everything else** — localStorage tokens, client-only route gating, no lifecycle endpoints, no cache hygiene on logout, RBAC defined but enforced on 2 of ~12 routers. This is the one area that needs completion, not just fixes.
2. **Enforcement layers are half-built** — three roles exist; two endpoints check them. Concurrency caps exist; inbound bypasses them. Terminal-status guards exist; one endpoint lacks one. The pattern: the invariant is known but not uniformly applied.
3. **All-client Next.js** — the app is effectively a Vite SPA wearing Next's runtime: no streaming, no SSR, `/auth/me` waterfall before anything renders. Acceptable for a dashboard; not worth a rewrite — convert data pages to RSC incrementally only if a public shell appears.
4. **In-process side effects** — analysis + webhooks in `BackgroundTasks` couple request lifecycle to durability. Fine at MVP scale; the durability fix (queue) is architectural, not cosmetic.
5. **Config drift risks** — `JWT_ALGORITHM`/token-expiry vars read by `config.py` but absent from `.env.example`; region requirement documented in LATENCY.md but not DEPLOYMENT.md; `config.yaml` referenced by chatterbox compose but never committed.
6. **Duplication/footguns** — two `formatMs` with different units; `Number(e.target.value)` pattern repeated; dead primitives shipped.

**Verdict:** no rewrite justified anywhere. Finish the enforcement layers; the bones are good.

---

## 9. Performance Findings — Top 10, ranked by impact ÷ effort

| # | Problem | Evidence | Impact | Effort |
|---|---|---|---|---|
| 1 | Bare `new QueryClient()` — `staleTime: 0` + refetch-on-focus storms; `useCalls` polls every 5s **unconditionally**, even when all calls are terminal | `providers.tsx:10`, `hooks.ts:203-208` | High — duplicate requests, INP, battery | XS |
| 2 | `livekit-client` (~150KB gzip) statically imported into agent-edit and call-detail chunks, used only on click | `test-call-panel.tsx:3`, `calls/[id]/page.tsx:3` | High — bundle/INP on flagship pages | XS (`await import`) |
| 3 | Login does `POST /auth/login` then `/auth/me` sequentially | `auth-context.tsx:44-50` | Medium — perceived TTFB | XS (return user in login response) |
| 4 | Auth context value not memoized; provider wraps entire app | `auth-context.tsx:74`, `providers.tsx:14` | Medium — whole-app re-renders | XS (`useMemo`) |
| 5 | No pagination on calls list/transcript — full list fetched and rendered | `calls/page.tsx:201-221`, `hooks.ts:203-209` | Medium — DOM size at scale (backend already supports limit/offset) | S |
| 6 | In-flight refresh dedup missing (correctness + perf) | `api.ts:34-49` | Medium | S |
| 7 | No security/caching headers; no `next.config.ts` optimization | `next.config.ts` (empty) | Medium | XS |
| 8 | Geist loaded latin-only — Arabic brand/RTL text falls back (FOUT) | `layout.tsx:7-15` | Low-Medium | XS |
| 9 | Backend: no idempotency on `call_events` — retried batches double-insert (transcript bloat) | `worker/api_client.py:80-117` | Low-Medium | S |
| 10 | `useHealthConfig` fetched inside `TestCallPanel` after agent query resolves (sequential waterfall) | `test-call-panel.tsx` | Low | XS |

**Backend perf is otherwise sound:** indexes match query patterns (composite indexes in `b8e2f1a4c6d0` map exactly to list/analytics/concurrency queries); pagination bounded (`le=200`); httpx timeouts everywhere; no N+1 found; Redis cache on the expensive voice-catalog fetch. **Voice pipeline:** well-instrumented (per-turn timings → `call_events`, p50/p95 columns), but the region requirement is under-documented in deploy docs and the latency logs are dropped by the missing logging config — regressions would be invisible.

---

## 10. Database & API Findings

**Schema/design (mostly solid):** org-scoped everything; FK set-null behavior for `inbound_agent_id` handled in a dedicated migration; enums for direction/status/roles; `call_events` as the transcript (append-only event log) is a good fit; `Numeric(10,4)` for cost. Indexes match queries.

**Issues:**

| Severity | Finding | Evidence | Fix |
|---|---|---|---|
| P1 | `PhoneNumber.e164` globally unique but duplicate-check is org-scoped → cross-org collision = unhandled 500 | `models/phone_number.py:19`, `numbers.py:55-61` | Catch IntegrityError, return 409 with clear message (and decide: should two orgs ever hold the same DID?) |
| P2 | `CallEventsBatchIn.events` unbounded in count/size — a worker (or token thief) can push arbitrarily large batches | `schemas/internal.py` | Bound batch size/count; reject with 422 |
| P2 | No idempotency key on `call_events` — retried batch after a lost response double-inserts transcript turns | `worker/api_client.py:80-117` | Client-generated batch id + unique constraint/upsert |
| P2 | Webhook payload type inconsistency (`cost_estimate` as string via `default=str`) | `internal.py:222-231`, `webhook_dispatch.py:32` | `float(call.cost_estimate)` before serialize |
| P2 | Deleting a phone number with call history → unhandled IntegrityError 500 (unlike `delete_agent`, which handles it) | `numbers.py:96-104` vs `agents.py:209-216` | Uniform IntegrityError handling |
| P2 | `ambience_clips` filename stored unbounded into `String(200)` → DataError 500 | `ambience.py:97` | Clamp/sanitize filename |
| P3 | Migration downgrade broken (unnamed constraint) | `alembic/versions/cbbb8ddee9b7_...py` | Name constraints explicitly |
| P2 | Naive/aware datetime handling is deliberately normalized everywhere checked — OK, but it's convention, not enforcement | `calls.py:102-106,377-379` | Consider `DateTime(timezone=True)` everywhere + a lint rule |

**API design (mostly solid):** consistent response schemas, no PII leakage, sensible status codes, bounded pagination, dispatch-failure consistency handled well (call marked failed + orphaned room deleted, `calls.py:290-308`). **Gaps:** no global exception handler or request-id middleware (unhandled errors become bare 500s — several confirmed above); rate limiting only on login; no save-time validation for webhook-tool URLs (discovered mid-call); webhook delivery is fire-and-forget with no delivery log; `/health/config` exposes integration inventory anonymously.

---

## 11. Reliability Findings — failure-mode walkthrough

| Failure | What happens today (evidence) | Verdict |
|---|---|---|
| Postgres unavailable | `/health` still returns `{"status":"ok"}` (`main.py:66-68`) — Railway keeps routing traffic; every request 500s | **Gap:** add deep readiness probe |
| Redis unavailable | Rate limiter and voice cache fail open (`cache.py:49-58`) — deliberate, documented | OK by design |
| Groq/TTS provider down mid-call | Exception → cleanup → `complete_call(end_reason="completed")` (P0) — false success, fake duration, webhooks fired | **Critical gap** |
| LiveKit dispatch failure | Call row marked failed + orphaned room deleted (`calls.py:290-308`) | Good |
| Worker crash mid-call | Lazy reaper marks call failed with `worker_lost` after max-duration + 120s | Acceptable; slow |
| API restarts mid-webhook/analysis | In-process `BackgroundTasks` lost; single attempt; no delivery record (`internal.py:278`) | **Gap:** durable queue |
| Customer webhook endpoint down | One attempt, 10s timeout, logged-and-gone (`webhook_dispatch.py:26-29`) — and the log may not emit (logging gap) | **Gap:** retries + delivery log |
| Event batch retried after lost response | Double-inserted transcript turns (no idempotency) | Gap |
| Recording egress fails | `recording_key` simply absent; no retry, no surfacing | Gap (silent) |
| `sip.callStatus` flips before listener registers | Missed → 45s wait → false `no_answer` (`agent.py:163-181`) | Gap (re-check after subscribe) |
| Concurrent outbound dispatches | Advisory lock serializes — but the lock is released by a mid-request commit in the reaper (`calls.py:113-114,222-235`) | **Gap:** narrow race reopens |
| SIGTERM | `exec uvicorn` forwards signals; worker `_cleanup` flushes reporter and reports completion; shutdown-aware retry | Good |
| Late `/answered` after `/complete` | Terminal call resurrected to `in_progress` | **Gap** (P1) |

**Root cause pattern:** the invariants exist (terminal statuses, locks, idempotent design) but are applied inconsistently across endpoints — each gap is a place the convention wasn't enforced.

---

## 12. UX & Accessibility Findings

**Flow maps (Entry → Goal → Steps → Friction → Drop-off → Improvement):**

- **Activation:** register → first working agent → long blank form, no templates, no confirm-password field → empty state with no CTA → high abandonment → onboarding checklist ("Create agent → Test call → Add number"), agent templates (Receptionist / Appointment booking, EN+AR), CTA in the empty state.
- **Agent builder (flagship):** edit agent → ~30 controls in one flat 734-line form → free-text model name (typo bricks the agent), silent JSON discard, no unsaved-changes guard, Save at the very bottom → errors + overwhelm → Basic/Advanced sections, model as select, block submit on invalid JSON, sticky save bar.
- **Test call (best-designed moment):** try the agent → preflight misconfiguration banner + free/no-number framing → no mic-permission primer, no link from the test call to its transcript, below the fold on mobile → close the loop: deep-link test call → transcript.
- **Numbers (worst friction):** connect a real number → buy DID in carrier dashboard → read a repo-path doc referenced as unlinked prose → paste E.164 + an internal LiveKit trunk ID → no validation, no verification, no test-inbound → PSTN adoption killer → guided wizard, E.164 validation, doc links, later managed provisioning.
- **Settings:** invite/keys/webhooks → good shown-once secret patterns but no copy buttons; invite hardcodes role, no member removal; `last_used_at` collected but never shown → copy buttons, role picker, removal, display last-used.
- **Destructive actions:** native `confirm()` everywhere; number-assignment select mutates immediately on change — one misclick silently reroutes inbound calls → confirmation dialog + undo/confirm on assignment.

**Accessibility:**
- **High:** Selects unlabeled to screen readers across the flagship form — `<Label htmlFor>` targets a `<button>` (`select.tsx:40`); affects Language, TTS provider, Voice, Greeting mode, Ambience, and per-row inbound-agent selects. Fix with `aria-labelledby`.
- **High:** hidden file input unreachable by keyboard/AT (`agent-form.tsx:596-601`).
- **Medium:** touch targets 24–32px on destructive table actions (`button.tsx:23-30`) — below the 44px norm, one tap from `confirm()`; mobile nav clipping is also an a11y failure.
- **Low:** raw `<label>` with no association on calls filters; placeholder-only inputs on the numbers form; `<html lang="en">` hardcoded, no `dir`, no Arabic UI locale (RTL *content* via `dir="auto"` is correctly done — prompt, greeting, transcripts, agent cards); h1→h3 skips; charts lack text alternatives. **Color-only status: none found — good.**

---

## 13. Testing Gaps

**Covered (genuinely good, ~3.2k lines):** org scoping/IDOR (`test_calls.py:616`, `test_webhooks.py:55`), concurrency caps incl. platform-wide provider cap, stale-call reaping, dispatch-failure cleanup, webhook SSRF rejection at creation, recording presigning, worker tools/pipeline/latency units, call-completion side effects.

**Untested:** team router (invite, role enforcement, org rename); api_keys router (creation, owner-identity authentication, revocation); ambience upload + worker ambience cache/traversal; seed script (would catch the missing `await`); SSRF edge cases (IPv6/CGNAT/rebind/redirect); webhook dispatch signing/delivery; login rate limiting; JWT type-confusion (refresh-as-access); terminal-state guard on `/answered`; cross-org unique-constraint handling; alembic upgrade/downgrade against real Postgres; worker entrypoint integration (answer-wait, no_answer, cleanup reporting); **everything frontend** (no tests at all); no E2E.

**Minimum Critical Regression Suite:**

1. **Auth lifecycle:** register → login → me → refresh → (new) logout/revocation; cross-org access blocked on every router (extend the existing IDOR pattern); role matrix: member cannot create API keys / manage team.
2. **Call lifecycle truth:** pipeline failure ⇒ `status=failed, end_reason=pipeline_error` (never completed); `/answered` after `/complete` is a no-op; dispatch failure ⇒ failed + room cleaned.
3. **Concurrency:** per-org cap and provider cap hold under parallel requests (the advisory-lock path); inbound documented behavior.
4. **Webhook tool SSRF:** private/loopback/link-local/CGNAT/IPv6 rejected at save AND at dispatch.
5. **Webhooks out:** signature header verifiable; delivery recorded; retry schedule honored (once persistence lands).
6. **Migrations:** `alembic upgrade head` from empty + `alembic check` drift gate in CI against Postgres.
7. **Seed smoke:** `make seed` idempotent, produces a working login.
8. **Frontend smoke (Playwright, later):** register → create agent → (mocked) test-session token; form invalid-JSON blocks save; mobile nav usable at 375px.

---

## 14. Monitoring & Developer Experience

**Blind spots (all Confirmed):**

- **No logging configuration anywhere** — uvicorn configures only its own loggers; `BOL.*` INFO logs (including per-turn latency telemetry, `agent.py:407`) hit a handler-less root logger and are silently dropped on the API. No structured/JSON logs, no request IDs — correlating one call across api↔worker is manual.
- **No error tracking** (zero Sentry/OTel references), no metrics endpoint, no tracing, no uptime/alerting, no webhook delivery monitoring, no audit logs (grep-verified absent).
- **Latency data is stored but never watched** — p50/p95 columns exist; nothing alerts on regression.
- **`/health` doesn't check the DB** — an instance with a dead Postgres passes Railway's healthcheck and 500s every request.

**Developer experience:**
- Broken on the maintainer's own machine: `Makefile` assumes `.venv/bin/activate` (Windows uses `Scripts\`); no `install`/bootstrap target; `make seed` broken (P0).
- Non-reproducible: no backend lockfile; unpinned CI toolchain; no pip cache; Actions tag-pinned.
- CI gaps: no Docker build job, no migration gate, no `ruff format --check`, no vuln scanning (`pip-audit`/`npm audit`), no coverage reporting, SQLite-only tests.
- Good: `.env.example` is thorough and honest; DEPLOYMENT.md per-service env matrix is genuinely good; entrypoint runs migrations with `exec` and IPv6 bind; both `.dockerignore`s exclude `.env*`.

---

## 15. Competitor Comparison

*(Product capabilities only; pricing/features from vendor pages fetched 2026-08-19; Arabic support for Retell/Bland and some funding figures UNVERIFIED. Competitors: Vapi = developer voice infra; Retell = SMB/agency call automation; Bland = enterprise/regulated; Dograh = closest OSS direct competitor.)*

| Capability | Us (BOL) | Vapi | Retell AI | Bland AI | Opportunity |
|---|---|---|---|---|---|
| All-in $/min | ~$0.02–0.06 target | ~$0.13–0.30 realistic ($0.05 platform fee) | $0.07–0.31 | $0.11–0.14 flat | In-product cost transparency dashboard vs estimated managed-stack cost |
| Self-host / data ownership | ✅ core design | ❌ | Enterprise only | Enterprise only | PDPL/sovereignty deployment recipes (KSA/UAE) |
| Arabic | ✅ native stack (Qwen3 + Whisper v3 + Chatterbox Multilingual) | DIY config only | Generic multilingual; Arabic unverified | 40+ langs, Arabic unverified | Productize: dialect voices, RTL dashboard, Gulf templates — Twilio's AI layer lacks Arabic entirely |
| First-run experience | Docker + 3 external accounts + trunk setup | Minutes, managed | Minutes ($10 credit, **live demo call widget**) | Days (FDE-led) | Zero-config browser demo with bundled trial keys (Dograh already does this) |
| Agent testing/QA | Basic test call | Monitoring/analytics | Simulation testing | Scenario testing | Simulated-call regression suite — no good OSS equivalent exists |
| Workflow/automation | Webhook tools + KB | Squads/workflows, broad API | Batch calling, preset functions, warm transfer | Conversational Pathways, omnichannel | Batch outbound campaigns + scheduled calls |
| Integrations | Generic webhook tool only | Many providers per layer | CRM/calendar presets | CRM/scheduling | MCP server so coding agents build BOL agents (Dograh's growth hack) |
| Reliability story | Self-managed | 99.9%+, 1B calls | SOC2 II, HIPAA | 99.99%, own carrier | Durable webhooks + health dashboard first; SLAs later |
| Compliance | DIY (you own the data) | SOC2, HIPAA +$2k/mo | SOC2 II, HIPAA, GDPR | SOC2 II, HIPAA, PCI, residency | Self-host security checklist + audit logs; certs only if managed cloud ships |
| Onboarding UX | Empty state, blank form | Docs-first | Demo-first, personas, templates | Enterprise timeline | Onboarding checklist + EN/AR templates + demo-first |

**Answers to the competitive questions:** (1) *They do better:* onboarding speed, managed reliability, compliance certs, integration counts, QA tooling, default voice polish. (2) *We do better:* 3–10× cost, data ownership, Arabic stack, BYO-everything, hackability. (3) *We're missing:* demo-first first-run, batch campaigns, QA simulation, durable webhooks, any notification system. (4) *They're missing:* productized Arabic, true self-host at $0 license, wholesale BYO-carrier economics, pricing transparency. (5) *Users likely dislike:* per-minute bill shock and cost opacity (Bland built a public teardown of Vapi/Retell pricing), lock-in, enterprise-gating of on-prem. (6) *Switching becomes compelling* when: real cost dashboard + one-command self-host + Arabic quality + migration guide from Vapi/Retell configs. (7) *Hard to copy:* open-weight GPU stack at ~$0.02/min, air-gapped deployments, Gulf-dialect model co-evolution, community forks. (8) *Activation:* zero-config demo. (9) *Retention:* QA simulation + analytics/alerts on data already collected. (10) *Satisfaction:* reliable webhooks, honest call records, Arabic voices that don't sound like an afterthought.

---

## 16. Missing Features

*(Problem solved → target user → user value → business value → impact → difficulty → dependencies → risks → why priority.)*

### A. Core Product Improvements
1. **Durable webhook delivery + delivery log UI** — silent event loss on every deploy → integrators → trust in the platform → retention vs managed rivals → High → M → Redis queue → queue ops complexity → integrations are the stickiness layer. **P1**
2. **Batch outbound campaigns (CSV/API, scheduling, per-campaign concurrency)** — one-off outbound only → ops users → run reminder/survey campaigns → Retell charges +$0.005/dial for exactly this → High → M → durable queue → spam risk needs rate limits → outbound is the revenue use case. **P2**
3. **Managed number provisioning (Telnyx purchase/search API)** — worst activation friction → serious users → number in minutes not days → unlocks PSTN adoption → High → M → Telnyx account API → billing/abuse controls needed → removes the activation cliff. **P1→P2**
4. **Call recording controls + surfacing** — egress failures are silent; recording is a bare `<audio>` at page bottom → operators → reliable records, playback where expected → support/compliance trust → Medium → S → S3 → — → recordings already 90% built. **P2**

### B. User Experience Features
5. **Onboarding checklist + agent templates (EN/AR)** — blank-prompt abandonment → new users → first agent in 2 minutes → activation → High → S → — → template quality matters → cheapest activation win. **P1**
6. **Error/empty/loading states everywhere + `error.tsx`** — 500 renders as "no data" → all users → trust, debuggability → fewer false "it's broken" impressions → Medium → S → — → — → basic product hygiene. **P1**
7. **Number-setup wizard** (validation, doc links, test-inbound button) → see A3. **P1**
8. **Test-call → transcript loop** (deep links both ways) → new users → see what the agent did → activation "aha" → Medium → XS → — → — → closes the core loop. **P1**

### C. Automation Features
9. **Scheduled/recurring outbound calls** — no time-based triggering → clinics/logistics → appointment reminders without external cron → retention → Medium → M → queue + scheduler → timezone bugs → natural pair with A2. **P2**
10. **Webhook retry policies + dead-letter replay** → integrators → recover missed events → trust → Medium → S → A1 → — → table stakes vs managed platforms. **P1**

### D. Retention Features
11. **Call analytics dashboards + threshold alerts on stored latency/outcome data** — data collected, never watched → operators → see quality/cost trends → daily-active value → High → S→M → REL logging fix → — → cheapest retention feature (data exists). **P1**
12. **Post-call analysis trends + quality scoring across calls** — analysis is per-call only → QA teams → fleet-level insight → stickiness → Medium → M → existing analysis service → LLM cost → extends an existing differentiator. **P2**

### E. Collaboration Features
13. **Real RBAC** (role matrix, role picker on invite, member removal, `is_active`) — privilege escalation + no offboarding → any multi-user org → safe collaboration → enterprise readiness → High → M → auth overhaul → — → security prerequisite. **P0/P1**
14. **Audit log** (who created/deleted agents, keys, numbers) — zero accountability trail (grep-verified absent) → org owners → incident forensics → compliance story → Medium → M → — → volume → required for any serious team. **P2**

### F. Admin & Operations Features
15. **Ops health dashboard** (active calls vs caps, provider error rates, webhook failures, queue depth) — currently flying blind → self-hosters + us → see trouble before users report it → reliability reputation → High → M → REL-001 metrics → — → the platform's own cockpit. **P1**
16. **Dead-letter/failed-delivery admin view + manual replay** → support → self-serve recovery → support load ↓ → Medium → S → A1 → — → pairs with durable webhooks. **P2**

### G. AI/Intelligence Features (only where genuinely useful)
17. **Agent evaluation/simulation suite** — no way to regression-test prompt changes → power users/agencies → test agent vs scripted scenarios before deploy → Synthflow charges enterprise for this; no good OSS equivalent → Very High → L → worker + LLM judge → judge cost/determinism → the one product gap that leapfrogs rather than copies. **P2**
18. **Prompt-improvement suggestions from failed-call analysis** — failed calls are invisible today (P0 bug makes them invisible twice) → builders → fix agent behavior from evidence → quality retention → Medium → M → BUG-001 first → garbage-in risk until P0 fixed → only after call records are truthful. **P3**

### H. Competitive Differentiators
19. **MCP server + coding-agent skill** — agents built by Claude Code/Cursor against BOL → developers → zero-UI agent building → Dograh's proven growth loop, executed with Arabic+telephony depth → High → M → stable API → API surface churn → cheapest distribution hack available. **P2**
20. **Arabic-first productization** (dialect voice demos, RTL dashboard locale, Gulf carrier setup recipes, PDPL self-host guide) — no competitor productizes Arabic; Twilio's AI layer lacks it entirely → GCC businesses → a tool that speaks their customers' language properly → uncontested category → Very High → M–L → TTS tuning → over-promising dialect quality → the strategic moat. **P1 strategic**
21. **Air-gapped/sovereign deployment profile** (single compose/helm, no external calls) — regulated/government buyers → procurement-ready self-host → deals managed rivals can't take → High → M → self-hosted STT/TTS (Phase 6) → support burden → hard to copy, high willingness to pay. **P3**

---

## 17. Top 20 Quick Wins

1. `await hash_password(...)` in `seed.py:48` + seed smoke test. *(XS)*
2. Fix `end_reason` reporting — pipeline errors ≠ completed (`worker/agent.py:251`). *(S)*
3. Terminal-status guard in `mark_call_answered` (`internal.py:156`). *(XS)*
4. UUID-validate ambience `clip_id` (`worker/ambience.py`, `schemas/agent.py`). *(XS)*
5. IntegrityError handling on numbers/ambience routes (kills 500s). *(S)*
6. QueryClient defaults + poll `useCalls` only while calls are active. *(XS)*
7. Dynamic-import `livekit-client` on click. *(XS)*
8. In-flight refresh dedup + global 401→logout + `queryClient.clear()` on logout. *(S)*
9. Stable keys on webhook-tool editors + block save on invalid JSON. *(S)*
10. CTA button inside the agents empty state. *(XS)*
11. Copy-to-clipboard on every shown-once secret. *(XS)*
12. Mobile nav collapse (hamburger below `md`, hide email). *(S)*
13. `aria-labelledby` on all Selects; label the numbers-form inputs. *(S)*
14. Error states on every page + `error.tsx`/`not-found.tsx`. *(S)*
15. LLM model free-text → select of valid models. *(XS)*
16. CI: Postgres `alembic upgrade head` + drift check; docker build ×3; pip cache; `timeout-minutes`. *(S)*
17. `uv lock` + use it in Dockerfile/CI. *(S)*
18. `dictConfig` logging with request IDs + Sentry hook. *(S)*
19. Commit/fix `deploy/chatterbox/config.yaml`; fix Makefile for Windows (`python -m` style). *(XS)*
20. Login response returns the user (kill the `/auth/me` waterfall); display API-key `last_used_at`; role picker on invite. *(S)*

---

## 18. Top 10 Strategic Improvements

1. **Truthful call records** (end_reason, terminal guards, idempotent events) — every downstream feature inherits this data.
2. **Auth overhaul:** cookie refresh token, rotation + revocation, logout, password reset, `is_active`, real RBAC.
3. **Durable side effects:** Redis-backed queue for webhooks + analysis, with retries, delivery log, dead-letter replay.
4. **Observability baseline:** structured logging + request IDs + Sentry + health/ready probes + latency alerting.
5. **Activation redesign:** onboarding checklist, EN/AR templates, test-call→transcript loop, number wizard.
6. **Reproducible delivery:** lockfiles, migration gate, docker builds in CI.
7. **Zero-config first run:** browser test call with bundled trial keys, no signup (match Dograh/Retell friction).
8. **Arabic-first productization:** dialect demos, RTL locale, GCC carrier recipes, PDPL deployment story.
9. **Agent QA simulation suite** — the leapfrog feature no OSS rival has.
10. **Sustainability path:** managed-cloud waitlist + paid support — avoid Vocode's fate (abandoned OSS).

---

## 19. Top 10 Features That Could Make Us Better Than Competitors

1. **Simulated-call QA/regression suite** (Synthflow has it enterprise-gated; no OSS equivalent).
2. **Zero-config browser demo with bundled keys** (matches Dograh; beats Vapi's docs-only start).
3. **Arabic-first productization** (nobody — not even Twilio — owns Arabic voice AI).
4. **In-product cost transparency dashboard** (self-host actuals vs estimated managed-stack cost — weaponizes their opacity).
5. **MCP server + coding-agent integration** (agents built from Claude Code/Cursor).
6. **Batch campaigns + scheduling at wholesale carrier rates** (Retell charges premiums for this).
7. **Air-gapped sovereign deployment profile** (deals Bland/Retell can only take at enterprise prices).
8. **Durable webhooks with delivery log + replay** (reliability table stakes, done right, open).
9. **Fleet-level Arabic analytics** (dialect-aware quality/latency reporting on data already collected).
10. **One-command full-stack self-host including GPU speech** (the Phase-6 story packaged; Pipecat/LiveKit are frameworks, not products).

---

## 20–22. Roadmaps

### 30 days — stabilize + trust the data
Quick wins 1–20. Auth overhaul phase 1 (cookie token, rotation, logout, `is_active`). Logging + request IDs + Sentry. Durable webhook queue (MVP: Redis list + retry worker + delivery log table). CI: lockfile, migration gate, docker builds. Onboarding checklist + templates + empty-state CTA. Error states + `error.tsx`. Minimum regression suite §13 items 1–3, 6–7.

### 60 days — activate + harden
RBAC matrix + member removal + audit log. SSRF pin-to-validated-IP. Rate limits on all sensitive endpoints. Number-setup wizard + E.164 validation; Telnyx provisioning spike. Test-call→transcript loop. Ops health dashboard v1 (caps, provider errors, webhook failures). Analytics dashboard + latency alerts on stored data. Mobile nav + a11y fixes. Playwright smoke suite. Regression suite items 4–5, 8.

### 90 days — differentiate
Zero-config demo (trial key pool). Batch campaigns MVP + scheduling. Agent QA simulation alpha. Arabic productization phase 1 (RTL locale, dialect demo line, GCC carrier recipes). MCP server. Managed-cloud waitlist. Postgres-backed CI job. Recording reliability (egress retry + surfacing).

---

## 23. Implementation Backlog

| ID | Task | Category | Priority | Impact | Effort | Dependencies | Suggested Owner |
|---|---|---|---|---|---|---|---|
| BUG-001 | end_reason reporting: pipeline errors ≠ completed | Bug | P0 | Very High | S | — | Backend |
| BUG-002 | seed.py missing await + smoke test | Bug / DX | P0 | High | XS | — | Backend |
| SEC-001 | Cookie refresh token + rotation/revocation/logout + CSP + `is_active` | Security | P0 | Very High | M | — | Full-stack |
| SEC-002 | SSRF: pin connection to validated IP; block CGNAT; re-check redirects | Security | P0 | High | S | — | Backend |
| SEC-003 | RBAC: API-key role check + permission matrix + invite role picker + member removal | Security | P0 | High | M | SEC-001 | Backend |
| REL-001 | uv lock + Dockerfile/CI; docker build job; alembic upgrade+drift gate in CI | Reliability | P0 | High | S | — | DevOps |
| BUG-003 | Terminal-status guard on mark_call_answered | Bug | P1 | High | XS | — | Backend |
| BUG-004 | Advisory-lock reap commit race | Bug | P1 | Medium | S | — | Backend |
| BUG-005 | IntegrityError handling (e164, number delete, ambience filename) | Bug / API | P1 | Medium | S | — | Backend |
| SEC-004 | Ambience clip_id UUID validation (traversal) | Security | P1 | High | XS | — | Backend |
| SEC-005 | Rate limits on register/refresh/api-key/outbound/test-session/knowledge | Security | P1 | High | S | Redis | Backend |
| SEC-006 | Password reset flow (requires email/notification infra decision) | Security / Feature | P1 | High | M | email provider | Full-stack |
| REL-002 | dictConfig logging + request IDs + Sentry | Monitoring | P1 | High | S | — | Backend |
| REL-003 | Durable webhook/analysis queue + retries + delivery log + replay | Reliability | P1 | High | M | Redis | Backend |
| REL-004 | Deep readiness probe (/health/ready checks DB) | Reliability | P1 | Medium | XS | — | Backend |
| DB-001 | Idempotency key on call_events; bound batch size | Database / API | P1 | Medium | S | — | Backend |
| API-001 | Global exception handler + request-id middleware; uniform 409s | API | P1 | Medium | S | REL-002 | Backend |
| API-002 | Webhook payload consistency (cost as number) + timestamp/delivery-id headers | API | P2 | Medium | XS | — | Backend |
| PERF-001 | QueryClient defaults + conditional polling | Performance | P1 | High | XS | — | Frontend |
| PERF-002 | Dynamic-import livekit-client | Performance | P1 | High | XS | — | Frontend |
| PERF-003 | Calls list pagination (backend ready) | Performance | P2 | Medium | S | — | Frontend |
| UX-001 | Global 401 handling + logout cache clear + refresh dedup | Bug / UX | P1 | High | S | — | Frontend |
| UX-002 | Mobile nav collapse | UX | P1 | High | S | — | Frontend |
| UX-003 | Error/empty/loading states + error.tsx everywhere | UX | P1 | Medium | S | — | Frontend |
| UX-004 | Onboarding checklist + EN/AR agent templates + empty-state CTA | UX / Product | P1 | High | M | — | Frontend |
| UX-005 | Agent form: sections, sticky save, model select, unsaved-changes guard | UX | P1 | Medium | M | — | Frontend |
| UX-006 | Number-setup wizard (validation, doc links, test-inbound) | UX / Product | P1 | High | M | — | Full-stack |
| UX-007 | Test-call ↔ transcript deep links | UX | P1 | Medium | XS | — | Frontend |
| BUG-006 | Tool editor stable keys + block save on invalid JSON | Bug | P1 | Medium | S | — | Frontend |
| A11Y-001 | aria-labelledby on selects; label all inputs; 44px destructive targets | Accessibility | P1 | Medium | S | — | Frontend |
| TEST-001 | Minimum regression suite §13 (authz matrix, call truth, concurrency, migrations, seed) | Testing | P1 | High | M | BUG-001/003 | Backend |
| TEST-002 | Playwright smoke: register→create agent; invalid-JSON block; 375px nav | Testing | P2 | Medium | M | — | Frontend |
| MON-001 | Ops health dashboard (caps, provider errors, webhook failures) | Monitoring | P1 | High | M | REL-002/003 | Full-stack |
| MON-002 | Latency/outcome alerting on stored columns | Monitoring | P2 | Medium | S | REL-002 | Backend |
| MON-003 | Audit log (agents, keys, numbers, members) | Monitoring / Security | P2 | Medium | M | — | Backend |
| FEAT-001 | Batch outbound campaigns + scheduling | Feature | P2 | High | M | REL-003 | Backend |
| FEAT-002 | Managed number provisioning (Telnyx API) | Feature | P2 | High | M | UX-006 | Backend |
| FEAT-003 | Agent QA simulation suite | Feature / Competitive | P2 | Very High | L | Worker | Backend |
| FEAT-004 | MCP server + coding-agent skill | Feature / Competitive | P2 | High | M | Stable API | Backend |
| FEAT-005 | Arabic productization phase 1 (RTL locale, dialect demos, GCC recipes) | Feature / Competitive | P1 | Very High | M | — | Full-stack |
| FEAT-006 | Zero-config browser demo (trial key pool, no signup) | Feature | P2 | Very High | M | Abuse controls | Full-stack |
| FEAT-007 | Analytics dashboards on stored call data | Feature | P1 | High | S–M | BUG-001 | Full-stack |
| FEAT-008 | Air-gapped deployment profile | Feature / Competitive | P3 | High | M | Phase 6 speech | DevOps |
| ARCH-001 | Complete auth lifecycle (reset, verification decision, deactivation) | Architecture | P1 | High | M | SEC-001/006 | Backend |
| ARCH-002 | Convert data pages to RSC incrementally (only if a public shell appears) | Architecture | P3 | Medium | L | — | Frontend |
| REL-005 | chatterbox config.yaml; non-root containers; SHA-pin Actions; Makefile Windows fix | Reliability / DX | P2 | Medium | S | — | DevOps |

---

## Final Decision Section

**If we only fixed 10 things:** (1) end_reason misreporting (BUG-001), (2) seed.py await (BUG-002), (3) cookie auth + rotation/revocation/logout (SEC-001), (4) SSRF TOCTOU (SEC-002), (5) RBAC/API-key escalation (SEC-003), (6) answered-resurrection guard (BUG-003), (7) CI lockfile+migration+docker gates (REL-001), (8) logging+Sentry (REL-002), (9) durable webhooks (REL-003), (10) frontend auth-lifecycle fixes — 401 handling, logout cache clear, refresh dedup (UX-001).

**Most dangerous problems in the codebase:** localStorage refresh tokens with no revocation; SSRF TOCTOU in a feature that POSTs LLM-chosen data to arbitrary URLs; owner-authenticating API keys mintable by any member; ambience path traversal; false-success call records poisoning every downstream system.

**Most likely to cause production failures:** a dependency release breaking the unpinned build; a broken migration deploying green (never exercised in CI); webhook/analysis loss on every deploy; blind debugging because INFO logs are dropped; the advisory-lock race under concurrent dispatch.

**Architecture areas that will hurt at scale:** in-process `BackgroundTasks` for side effects (move to a queue before volume grows); the shared `/internal` god-token (needs network isolation); unbounded `call_events` batches and unpaginated call lists; per-request bcrypt API-key auth under load; DB pool defaults once replicas grow.

**Biggest security risks:** token storage/revocation, SSRF TOCTOU, RBAC absence, ambience traversal, missing rate limits, `/internal` exposure. Fix rows 1–6 of §7 before real users.

**Biggest performance bottlenecks:** untuned TanStack Query (refetch storms + unconditional 5s polling), static `livekit-client` import, login waterfall, unpaginated calls list, duplicate transcript inserts on retry. Backend is otherwise in good shape.

**UX areas with most friction:** number setup (carrier dashboard + trunk-ID pasting), blank-prompt agent form with no templates, missing error states, broken mobile nav, silent JSON discard, no onboarding. The test-call panel is the best UX in the app — generalize its preflight-banner pattern.

**Important missing features:** password reset (and any email/notification system), logout, member removal, password-change, durable webhooks with delivery log, batch campaigns, QA simulation, ops health dashboard, audit log, zero-config demo, Arabic RTL locale.

**What competitors do better:** onboarding speed (Retell's live demo call, $10 credit), managed reliability/compliance, integration counts, QA tooling (Synthflow Test Center), default voice polish.

**What competitors are missing that we can exploit:** productized Arabic (Twilio's AI layer lacks Arabic entirely), true self-host at $0 license, wholesale BYO-carrier economics, honest cost transparency, OSS QA simulation.

**Hard for competitors to copy:** open-weight GPU stack at ~$0.02/min, air-gapped sovereign deployments, Gulf-dialect model co-evolution, community forks, wholesale carrier pass-through (it undermines their meter).

**Single highest-leverage feature to build next:** **truthful, durable call records + webhook delivery as one workstream** (BUG-001/003, DB-001, REL-003) — because every retention and intelligence feature (analytics, QA simulation, prompt suggestions, alerts) inherits the correctness of this data, and it is also the reliability story that makes integrators stay. If forced to pick a *user-facing* feature instead: the zero-config browser demo, because activation is the funnel's biggest leak.

**Explicitly do NOT waste time on:** rewriting the frontend to RSC (incremental only, and only if a public shell appears); building billing/payments before a managed offering exists; more speech-provider integrations; MFA/email-verification polish before password reset and basic lifecycle exist; chasing SOC2 before there is a managed product to certify; custom auth innovation beyond cookie+rotation+revocation; multi-region/self-hosted-LiveKit work before product-market evidence; a mobile app; Premature Arabic *dialect* tuning before the Arabic productization basics (RTL locale, demo line, GCC recipes) ship.

---

*Verification note: all P0 and P0-adjacent claims were confirmed by direct file reads during this audit (including `api.ts` token storage, `seed.py` missing `await`, `internal.py` missing terminal guard, and a grep-verified enumeration of auth endpoints). Items marked LIKELY need runtime confirmation. Competitor figures are as-of 2026-08-19 with UNVERIFIED items flagged in §15.*
