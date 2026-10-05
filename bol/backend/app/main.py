import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

logger = logging.getLogger("BOL.api")


def _validate_secrets() -> None:
    """jwt_secret/internal_service_token default to "change-me" so the app
    still boots for local dev without a .env file. Running with that default
    outside tests means anyone can forge JWTs or hit /internal/* directly —
    refuse to start rather than silently exposing that."""
    if "pytest" in sys.modules:
        return
    insecure = [
        name
        for name, value in (
            ("JWT_SECRET", settings.jwt_secret),
            ("INTERNAL_SERVICE_TOKEN", settings.internal_service_token),
        )
        if value == "change-me"
    ]
    if insecure:
        raise RuntimeError(
            f"Refusing to start: {', '.join(insecure)} still set to the default "
            "\"change-me\". Set a real secret in .env."
        )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Warms the knowledge-base embedding model at startup instead of on the
    # first request — without this, the first POST /knowledge or
    # /internal/knowledge/search after every deploy pays for a synchronous
    # multi-second (or, on a cold cache, multi-hundred-MB download) model
    # load. Best-effort: skipped under pytest (no real model available/
    # wanted in tests) and never fatal — a failure here just means the
    # first real request pays the cost instead of state up.
    if "pytest" not in sys.modules:
        from app.services.knowledge import warm_model

        try:
            await warm_model()
        except Exception:
            logger.exception("Failed to warm the knowledge-base embedding model at startup")
    yield


def create_app() -> FastAPI:
    _validate_secrets()
    app = FastAPI(title="BOL API", version="0.1.0", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/config")
    async def health_config() -> dict[str, bool]:
        """Which integrations are configured — booleans only, never secret
        values. Lets the frontend explain *why* a call/test-session failed
        instead of a generic error (missing LiveKit vs missing Groq vs both)."""
        livekit_configured = bool(
            settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret
        )
        return {
            "livekit": livekit_configured,
            "groq": bool(settings.groq_api_key),
            "fish": bool(settings.fish_api_key),
            "chatterbox": bool(settings.chatterbox_base_url),
            "sip_trunk": bool(settings.livekit_sip_outbound_trunk_id),
            "secrets": bool(settings.secrets_key),
        }

    from app.interruption import router as interruption_router
    from app.routers import (
        agents,
        ambience,
        analytics,
        api_keys,
        auth,
        calls,
        internal,
        knowledge,
        numbers,
        team,
        tools,
        voices,
        webhooks,
    )
    from app.tts_providers import router as tts_providers_router

    app.include_router(auth.router)
    app.include_router(agents.router)
    app.include_router(numbers.router)
    app.include_router(voices.router)
    app.include_router(tts_providers_router)
    app.include_router(interruption_router)
    app.include_router(ambience.router)
    app.include_router(calls.router)
    app.include_router(analytics.router)
    app.include_router(team.router)
    app.include_router(api_keys.router)
    app.include_router(webhooks.router)
    app.include_router(knowledge.router)
    app.include_router(tools.router)
    app.include_router(internal.router)

    return app


app = create_app()
