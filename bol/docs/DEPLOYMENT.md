# Deploying BOL to Railway

BOL is one monorepo, deployed as **four independent Railway services** sharing one
project: the API, the LiveKit worker, the frontend, and (optionally) self-hosted
Chatterbox TTS on a separate GPU host. Postgres and Redis are Railway-managed plugins.

```
Railway project "BOL"
├── Postgres (plugin)
├── Redis (plugin)
├── api        — backend/, Dockerfile, public domain
├── worker     — backend/, Dockerfile.worker, no public domain, no healthcheck
└── frontend   — frontend/, Dockerfile, public domain
                                                  (Chatterbox: separate GPU host, not Railway)
```

Each backend service builds from the same `backend/` directory but a different
Dockerfile — that's normal in a monorepo; Railway lets each service pick its own
root directory and Dockerfile path.

## 1. Create the project and databases

1. Create a new Railway project.
2. Add a **Postgres** plugin. Note the auto-generated `DATABASE_URL` reference
   (`${{Postgres.DATABASE_URL}}`) — you'll reference it, not copy the literal value.
3. Add a **Redis** plugin. Same idea (`${{Redis.REDIS_URL}}`).

## 2. Create the three services

For each, "New Service" → "GitHub Repo" → select this repo, then set:

| Service | Root Directory | Config file path |
|---|---|---|
| `api` | `backend` | `railway.api.json` |
| `worker` | `backend` | `railway.worker.json` |
| `frontend` | `frontend` | `railway.json` |

(If your Railway plan/version doesn't support "Config file path" for Dockerfile
selection, set the Dockerfile path directly in each service's Settings → Build
instead: `Dockerfile` for `api` and `frontend`, `Dockerfile.worker` for `worker`.)

Generate a public domain for `api` and `frontend` (Settings → Networking). **Do
not** generate one for `worker` — it never listens on HTTP, and Railway may mark
its deploys "unhealthy" if you attach a healthcheck it can't answer. `railway.worker.json`
deliberately has no `healthcheckPath`; if your Railway UI still shows a healthcheck
toggle for the service, turn it off explicitly.

## 3. Environment variables

Generate real secrets for `JWT_SECRET` and `INTERNAL_SERVICE_TOKEN` (e.g.
`openssl rand -hex 32`) — the app refuses to start with the default `"change-me"`
(`app/main.py:_validate_secrets`). Use the **same** `INTERNAL_SERVICE_TOKEN` on
`api` and `worker` — it's the shared secret between them.

`SECRETS_KEY` (api only — not needed on `worker`) encrypts Tool secret headers
(e.g. an `Authorization` bearer token an org enters for a webhook tool, see
`app/services/crypto.py`). Generate with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
Leaving it unset is fine for a deploy with no tools using secret headers —
saving one just fails with a clear error until it's set. Rotating it
invalidates any already-stored tool secrets (they decrypt to nothing rather
than erroring — resave affected tools after rotating).

### `api` service

```
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
JWT_SECRET=<generate>
INTERNAL_SERVICE_TOKEN=<generate — same value on worker>
SECRETS_KEY=<generate — see below>
CORS_ORIGINS=https://<frontend-public-domain>
# or, once you have a custom domain: CORS_ORIGINS=https://app.yourdomain.com

LIVEKIT_URL=wss://<project>.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
LIVEKIT_SIP_OUTBOUND_TRUNK_ID=...        # only for real PSTN outbound calls

GROQ_API_KEY=...
FISH_API_KEY=...                          # optional
CHATTERBOX_BASE_URL=...                   # optional, see §6

S3_BUCKET=...                             # optional, call recording — see §7
S3_REGION=us-east-1
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...

MAX_CONCURRENT_CALLS=5
```

`DATABASE_URL` from Railway's Postgres plugin is a bare `postgres://` URL — the
app normalizes this to `postgresql+asyncpg://` automatically
(`app/config.py:_normalize_database_url`), so paste it as-is.

`CORS_ORIGINS` accepts either a plain origin/comma-separated list (shown above) or
the JSON-array form used in `.env.example` — both work
(`app/config.py:_parse_cors_origins`).

`PORT` is injected by Railway automatically — don't set it yourself. The API binds
`::` (dual-stack) on that port so both Railway's public proxy (IPv4) and its
private network (IPv6-only, see below) can reach it.

### `worker` service

```
API_BASE_URL=http://api.railway.internal:${{api.PORT}}
INTERNAL_SERVICE_TOKEN=<same value as api>

LIVEKIT_URL=wss://<project>.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...

GROQ_API_KEY=...
FISH_API_KEY=...                          # optional
CHATTERBOX_BASE_URL=...                   # optional
```

`API_BASE_URL` uses Railway's private networking (`<service>.railway.internal`),
not the api service's public domain — private traffic doesn't leave Railway's
network and isn't rate-limited by your public domain. This only resolves over
IPv6, which is exactly why the api service binds `::` instead of `0.0.0.0`.

The worker doesn't need `DATABASE_URL` or `REDIS_URL` — it never opens its own DB
connection (`worker/api_client.py`).

### `frontend` service

Runtime variables: none required.

**Build variable** (Settings → set under Build, not the regular runtime Variables
tab — this is the part people miss):

```
NEXT_PUBLIC_API_URL=https://<api-public-domain>
```

`NEXT_PUBLIC_*` values are inlined into the JS bundle at `next build` time, not
read at container runtime — setting it as a normal runtime variable does nothing
(`frontend/Dockerfile`). If you change the API's domain later, you must trigger a
new build of the frontend, not just a redeploy.

## 4. First deploy

Deploy `api` first — its entrypoint (`backend/docker-entrypoint.sh`) runs
`alembic upgrade head` before starting, so the schema is created on that deploy.
Then deploy `worker` and `frontend`.

Check `api`'s `/health` returns `{"status": "ok"}` and `/health/config` shows which
integrations are configured (booleans only, no secrets — safe to check without auth).

## 5. Custom domains

Add custom domains to `api` and `frontend` under each service's Networking
settings (CNAME to Railway's provided target). If you change the frontend's
domain, update `CORS_ORIGINS` on `api` (runtime var, redeploy is enough — no
rebuild needed) and `NEXT_PUBLIC_API_URL` if the API's own domain changed
instead (rebuild required).

## 6. Chatterbox TTS — not on Railway

`deploy/chatterbox/` needs a GPU (the README sizes it at real-time only with one)
and Railway has none. Options:
- **Skip it.** `TTS_PROVIDER=groq` or `fish` — both fully hosted, no GPU needed.
- **Self-host it elsewhere** (RunPod, Lambda Labs, your own GPU box) and point
  `CHATTERBOX_BASE_URL` at it from both `api` and `worker`. Put it behind your own
  auth/network restriction — the vendored server has no auth of its own
  (`deploy/chatterbox/README.md`). The CPU-only Dockerfile variant in
  `deploy/chatterbox/vendor/` exists but runs well below real-time — don't use it
  for live calls.

## 7. Call recording (optional)

Leave `S3_BUCKET` blank to disable recording entirely (default). To enable it,
create a **private** S3 bucket (any region/provider that speaks the S3 API) and
set the four `S3_*` variables on `api`. The bucket must not be public — the API
presigns short-lived (5 min) playback URLs on demand
(`app/services/recordings.py`); nothing is ever stored as a permanent public URL.
The worker uploads via LiveKit egress directly to S3 using the same credentials
passed at call time — it does not need the `S3_*` vars itself.

## 8. Knowledge base

Runs inside the `api` service, not a separate one — local ONNX embeddings via
`fastembed`, no external API. The model is baked into the `api` image at build
time (`backend/Dockerfile`), so there's no first-request download delay. Budget
roughly an extra 500MB–1GB of image size and memory headroom on the `api` service
for the model.

## 9. Scaling notes

- **Worker replicas**: safe to run more than one — jobs are dispatched by
  LiveKit, not by BOL, so multiple workers just pick up different calls. Each
  needs the full `LIVEKIT_*`/`GROQ_API_KEY`/etc. env set (they're identical
  across replicas).
- **API replicas**: safe — stateless aside from the DB. Migrations only run once,
  from whichever replica's entrypoint runs first (harmless if it also ran on a
  second replica; Alembic takes its own lock).
- **Post-call analysis & webhook delivery** currently run as FastAPI background
  tasks inside the `api` process (`app/routers/internal.py`), not a durable
  queue. A deploy/restart mid-flight silently drops in-flight ones. Fine at low
  volume; if you need guaranteed delivery or are seeing analysis get dropped
  under load, move this to a Redis-backed queue (Redis is already provisioned
  and only used today for the voice-catalog cache and login rate limiting).

## 10. Smoke test checklist

After all three services are up:

- [ ] `GET https://<api-domain>/health` → `{"status": "ok"}`
- [ ] Register an org at `https://<frontend-domain>/register`
- [ ] Create an agent, run a browser test call (agent's page → "Start test call")
      — confirms `api` ↔ LiveKit ↔ `worker` ↔ Groq are all wired correctly
- [ ] If telephony is configured: place a real outbound call, confirm it
      connects and the transcript appears on the call detail page
- [ ] Add a webhook (Settings → Webhooks) and confirm `call.completed` is
      delivered after a call
- [ ] If S3 is configured: confirm a completed call shows a working recording
      player
