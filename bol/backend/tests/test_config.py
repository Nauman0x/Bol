"""Regression test for the bug where Settings loaded the wrong .env file
depending on the process's working directory at startup — env_file=".env"
resolved relative to CWD, so running uvicorn from backend/ silently skipped
the repo-root .env holding LIVEKIT_URL/GROQ_API_KEY. See app/config.py.
"""

from pathlib import Path

import app.config as config_module
from app.config import Settings


def test_env_file_paths_are_absolute_regardless_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    settings = Settings()
    env_files = settings.model_config["env_file"]

    assert len(env_files) == 2
    assert all(Path(f).is_absolute() for f in env_files)


def test_env_file_paths_point_to_repo_root_and_backend_dot_env():
    backend_dir = Path(config_module.__file__).resolve().parent.parent
    repo_root = backend_dir.parent

    settings = Settings()
    root_env, backend_env = settings.model_config["env_file"]

    assert Path(root_env) == repo_root / ".env"
    assert Path(backend_env) == backend_dir / ".env"


def test_backend_env_overrides_repo_root_env(tmp_path, monkeypatch):
    """backend/.env is meant to override shared root config for local dev
    (e.g. DATABASE_URL pointed at localhost) — later env_file wins."""
    root_env = tmp_path / "root.env"
    backend_env = tmp_path / "backend.env"
    root_env.write_text("SHARED_TEST_VALUE=from-root\n")
    backend_env.write_text("SHARED_TEST_VALUE=from-backend\n")

    class TestSettings(Settings):
        shared_test_value: str = "default"

        model_config = {"env_file": (root_env, backend_env), "extra": "ignore"}

    monkeypatch.delenv("SHARED_TEST_VALUE", raising=False)
    settings = TestSettings()
    assert settings.shared_test_value == "from-backend"


def test_database_url_bare_postgres_scheme_is_normalized_to_asyncpg():
    # Railway (and most managed Postgres providers) hand you a bare
    # "postgres://" URL — the asyncpg SQLAlchemy dialect needs "+asyncpg"
    # or create_async_engine raises at import time.
    settings = Settings(database_url="postgres://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+asyncpg://user:pass@host:5432/db"


def test_database_url_bare_postgresql_scheme_is_normalized_to_asyncpg():
    settings = Settings(database_url="postgresql://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+asyncpg://user:pass@host:5432/db"


def test_database_url_already_asyncpg_is_left_alone():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+asyncpg://user:pass@host:5432/db"


def test_cors_origins_accepts_json_array_string(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["https://a.com", "https://b.com"]')
    settings = Settings()
    assert settings.cors_origins == ["https://a.com", "https://b.com"]


def test_cors_origins_accepts_comma_separated_string(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.com,https://b.com")
    settings = Settings()
    assert settings.cors_origins == ["https://a.com", "https://b.com"]


def test_cors_origins_accepts_single_plain_origin(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.up.railway.app")
    settings = Settings()
    assert settings.cors_origins == ["https://app.up.railway.app"]
