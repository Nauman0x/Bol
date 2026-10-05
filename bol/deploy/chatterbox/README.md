# Self-hosted Chatterbox TTS (optional)

Runs [devnen/Chatterbox-TTS-Server](https://github.com/devnen/Chatterbox-TTS-Server)
— an OpenAI-compatible wrapper around Resemble AI's open-source Chatterbox
models — on your own GPU, as an alternative to the Fish Audio API. Skip this
entirely if you're only using Fish/Groq; nothing else in BOL depends on it.

## Why this is a separate thing

This directory is **not** part of the main `docker-compose.yml` at the repo
root, and there's no plan to merge it. Reasons:

- It needs an NVIDIA GPU. The API and worker don't, and run fine on cheap
  CPU instances — bundling them would force a GPU requirement onto every
  deploy.
- The model download (multiple GB) makes bring-up slow and occasionally
  flaky. You don't want that in the critical path of `docker compose up`
  for the app itself.
- You'll likely want to scale, restart, or upgrade it independently of the
  API/worker — different failure domain, different on-call story.

The worker reaches it over plain HTTP via `CHATTERBOX_BASE_URL`, exactly like
any other TTS provider — there's no tighter coupling than that.

## Sizing

Chatterbox **Turbo** (the engine this setup uses — see below) is a 350M
parameter model. ~8GB of VRAM is comfortably enough, and it runs at roughly
6x realtime, which works out to about **5–6 concurrent calls per GPU**. Plan
your `MAX_CONCURRENT_CALLS` (in the root `.env`) against that number if any
agents use Chatterbox — not against price, which is $0 marginal cost per
call once the box is running.

## Setup

1. **Clone the upstream server into this directory** (gitignored — this repo
   doesn't vendor someone else's source tree):
   ```bash
   git clone https://github.com/devnen/Chatterbox-TTS-Server deploy/chatterbox/vendor
   ```
2. **Start it:**
   ```bash
   cd deploy/chatterbox
   docker compose up -d --build
   ```
   First boot downloads model weights from Hugging Face — expect several
   minutes. Watch progress with `docker compose logs -f`.
3. **Switch the engine to Turbo.** The server supports three Chatterbox
   models (Original, Multilingual, Turbo) as a hot-swappable setting — it
   is not something to hand-edit in `config.yaml` (the exact schema varies
   by release, and a bad edit can silently fail to apply or break startup).
   Once the container is up, open the web UI at `http://<this-host>:8004`
   and select **Chatterbox Turbo** as the engine, or set it via
   `POST /save_settings` if you're scripting this. Confirm with:
   ```bash
   curl http://<this-host>:8004/api/model-info
   ```
4. **Add voices.** Chatterbox does zero-shot voice cloning from a 5–15s
   reference clip. Upload one via the web UI, or `POST /upload_predefined_voice`
   / `POST /upload_reference` directly. Voice ids you add here are what you'll
   pick from the "Chatterbox" provider's voice dropdown in the BOL
   agent-builder — the platform fetches them live from
   `GET /v1/audio/voices`.
5. **Point BOL at it.** In the repo-root `.env`:
   ```bash
   CHATTERBOX_BASE_URL=http://<this-host>:8004/v1
   CHATTERBOX_MODEL=chatterbox-turbo
   ```
   `/health/config` on the API will report `"chatterbox": true` once this is
   set. Agents can then select "Chatterbox (self-hosted)" as their TTS
   provider.

## Network

The OpenAI-compatible endpoint (`/v1/audio/speech`, `/v1/audio/voices`) has
**no authentication by default**. Don't expose port 8004 to the public
internet as-is. Either:
- Bind it to a private network the worker can reach but nothing else can
  (VPC peering, a WireGuard tunnel, Docker's own private network if the
  worker runs on the same host), or
- Put it behind a reverse proxy that adds auth (basic auth, an API-key
  header check, mTLS) and update `CHATTERBOX_BASE_URL` to point at the
  proxy instead.

## Honest caveat on latency

The worker reaches this server through its OpenAI-compatible endpoint using
`livekit-plugins-openai`, which does not support streaming
(`capabilities.streaming=False`) — so responses are still buffered
sentence-by-sentence before playback starts, same as Groq today. Turbo's low
per-request latency (~75ms) and high throughput (~6x realtime) partly make
up for that, but if it measurably lags Fish Audio's real streaming in
practice, the fix is a small custom LiveKit TTS plugin against this server's
native streaming `/tts` endpoint (`stream: true`) instead of the
OpenAI-compatible one — not built here, since it's only worth the extra code
if the measurement says so.
