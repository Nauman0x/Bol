from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Resolved by file location, not CWD — env_file=".env" would silently pick a
# different file depending on whether the process starts from the repo root
# or backend/, which is how LIVEKIT_URL/GROQ_API_KEY ended up never loading
# despite being set correctly in the repo-root .env. Root holds shared
# integration config (LiveKit, Groq); backend/.env is a local-dev override
# layered on top (e.g. DATABASE_URL pointed at localhost instead of the
# Docker Compose service name) — later files win in pydantic-settings.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", _BACKEND_DIR / ".env"),
        extra="ignore",
    )

    # core
    database_url: str = "postgresql+asyncpg://BOL:BOL@localhost:5432/BOL"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    internal_service_token: str = "change-me"
    # Fernet key encrypting Tool header secrets (app/services/crypto.py).
    # None means tool secret headers cannot be saved — see
    # SecretsKeyNotConfigured. Generate with
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
    secrets_key: str | None = None
    api_base_url: str = "http://localhost:8000"
    # NoDecode: pydantic-settings normally JSON-decodes list-typed env vars
    # and errors out on anything else — Railway (and most PaaS dashboards)
    # give you a plain string field, not a place to type a JSON array. The
    # validator below accepts either form.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        # Railway (and most managed Postgres providers) hand you a bare
        # "postgres://" or "postgresql://" URL — asyncpg's SQLAlchemy
        # dialect requires the "+asyncpg" driver suffix or create_async_engine
        # raises at import time ("the asyncio extension requires an async
        # driver"), which crashes the whole app before a single request.
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://") :]
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> list[str]:
        if isinstance(value, list):
            return value
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            import json

            return json.loads(text)
        # Plain comma-separated form, e.g. "https://a.com,https://b.com" —
        # the format Railway's dashboard actually makes easy to type.
        return [origin.strip() for origin in text.split(",") if origin.strip()]

    # livekit
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_sip_outbound_trunk_id: str = ""

    # groq
    groq_api_key: str = ""
    llm_model: str = "qwen/qwen3.6-27b"

    # fish audio — pay-as-you-go API, NOT the Plus subscription (2.8x more
    # expensive per minute). s2.1-pro-free is genuinely free but the window
    # is stated to end 2026-08-31 (already extended twice); switch to the
    # paid "s2-pro" (or successor) before then. Concurrency is gated by
    # prepaid API balance (5 concurrent under $100, 15 at $100+), not by
    # this setting.
    fish_api_key: str = ""
    fish_model: str = "s2.1-pro-free"

    # chatterbox — self-hosted, OpenAI-compatible server (devnen/Chatterbox-TTS-Server),
    # deployed separately (see deploy/chatterbox/). base_url should include the
    # /v1 suffix, e.g. http://gpu-host:8004/v1 — matches the openai plugin's
    # base_url convention.
    chatterbox_base_url: str = ""
    chatterbox_model: str = "chatterbox-turbo"

    # speech — stt_provider: livekit (streaming, default) | groq (batch,
    # fallback) | local (Phase 6). See docs/LATENCY.md for why livekit is
    # the default: Groq STT doesn't stream, adding ~360ms of serialized
    # per-turn latency that streaming STT removes.
    # tts_provider is the global default; individual agents can override it
    # via AgentConfig.tts_provider (see app/schemas/agent.py).
    stt_provider: str = "livekit"
    tts_provider: str = "groq"
    stt_service_url: str = "ws://localhost:8020"
    tts_service_url: str = "ws://localhost:8021"

    # call recording — LiveKit room-composite egress uploads to this S3
    # bucket (worker/agent.py), the API presigns short-lived GET URLs for
    # playback on demand (app/services/recordings.py) rather than exposing
    # the bucket directly or storing a permanent public URL.
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    # limits
    max_concurrent_calls: int = 5
    # Per-provider caps, platform-wide (not per-org) — Fish/Chatterbox
    # concurrency is gated by a shared API key/GPU pool, not per-tenant, so
    # these are checked against every org's active calls combined, unlike
    # max_concurrent_calls above. See .env.example for where these numbers
    # come from (Fish's prepaid tier, ~5-6 calls/GPU for Chatterbox Turbo).
    fish_max_concurrent_calls: int = 5
    chatterbox_max_concurrent_calls: int = 5


settings = Settings()
