import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 — populate Base.metadata
from app.config import settings
from app.db import Base, get_db, get_session_factory
from app.main import create_app


@pytest.fixture(autouse=True)
def _isolate_external_provider_keys(monkeypatch):
    """Tests must never depend on whatever real provider credentials happen
    to be sitting in the developer's .env — app/services/call_analysis.py
    fires a real Groq request whenever settings.groq_api_key is truthy, and
    other code does the same for fish/chatterbox. Blank them by default;
    individual tests opt back into a "configured" path with their own
    monkeypatch.setattr(settings, ..., "...") after this fixture runs."""
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "fish_api_key", "")
    monkeypatch.setattr(settings, "chatterbox_base_url", "")


@pytest.fixture
async def db_session_factory():
    # StaticPool + a single shared in-memory connection so all sessions in a test see
    # the same DB; SQLite needs FK enforcement turned on explicitly per-connection.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def app(db_session_factory):
    app = create_app()

    async def override_get_db():
        async with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    # BackgroundTasks that open their own session (e.g. internal.py's
    # complete_call finalizer) must land on the same in-memory test DB as
    # get_db, not the real one app.db.async_session_factory points at.
    app.dependency_overrides[get_session_factory] = lambda: db_session_factory
    return app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def register_and_login(client: AsyncClient, org_name: str, email: str) -> dict:
    resp = await client.post(
        "/auth/register",
        json={
            "org_name": org_name,
            "name": "Test User",
            "email": email,
            "password": "supersecret1",
        },
    )
    assert resp.status_code == 201, resp.text
    tokens = resp.json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}
