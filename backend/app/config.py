from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://bol:bol@localhost:5432/bol"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    internal_service_token: str = "change-me"
    api_base_url: str = "http://localhost:8000"

    cors_origins: list[str] = ["http://localhost:3000"]

    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    ai_provider: str = "stub"  # stub | groq
    groq_api_key: str = ""
    llm_model: str = "qwen/qwen3-32b"


settings = Settings()
