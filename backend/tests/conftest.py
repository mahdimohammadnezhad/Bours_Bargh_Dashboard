import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.session import Base, get_db


@pytest_asyncio.fixture
async def db_session():
    """Isolated in-memory SQLite DB per test - no external services required.

    market_service.record_cycle's upsert is dialect-aware (SQLite and
    PostgreSQL both supported - see market_service._DIALECT_INSERT), so it
    is exercised for real against this fixture, not just against a mocked
    session.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    # Import here (not module-level) so app.main's module-level setup_logging
    # etc. runs only once these are patched in, and so we can patch the
    # exact objects app.main holds references to.
    import app.main as main_module

    async def _noop() -> None:
        return None

    monkeypatch.setattr(main_module, "init_db", _noop)
    monkeypatch.setattr(main_module.collector_manager, "start", _noop)
    monkeypatch.setattr(main_module.collector_manager, "stop", _noop)
    monkeypatch.setattr(main_module, "maybe_run_historical_backfill", _noop)

    async def _override_get_db():
        yield db_session

    main_module.app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=main_module.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with main_module.app.router.lifespan_context(main_module.app):
            yield ac

    main_module.app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend():
    return "asyncio"
