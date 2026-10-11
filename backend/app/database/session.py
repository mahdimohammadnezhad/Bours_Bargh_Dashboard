import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

if engine.dialect.name == "sqlite":
    # SQLite's default rollback-journal mode lets a writer block every
    # reader (and vice versa) for the whole transaction. That's a real
    # problem here, not a theoretical one: collectors write every few
    # seconds, and under that sustained load a plain GET request could
    # queue behind writer locks indefinitely (observed as the dashboard's
    # own API hanging - not going slower, just never responding - during
    # local SQLite dev/testing per docs/TROUBLESHOOTING.md). WAL mode lets
    # readers proceed concurrently with a writer; busy_timeout makes any
    # remaining brief contention wait-and-retry instead of raising
    # "database is locked". PostgreSQL (production) has MVCC and never
    # needed this to begin with, so this only ever fires for SQLite.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001, ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


# WAL fixes readers vs. writer, but SQLite still allows only one writer at a
# time and fails the others with "database is locked" once busy_timeout
# runs out. Every writer here (collector cycles, startup backfills) lives in
# this one process, and in practice the first cycles overlapping the
# startup backfill (~900 + ~450 + ~400 row transactions) exceeded the
# timeout and lost those writes. Serializing write transactions in-process
# removes the contention instead of racing it.
_sqlite_write_lock = asyncio.Lock()


def db_write_lock() -> AbstractAsyncContextManager:
    """Hold around a write transaction. No-op on PostgreSQL."""
    return _sqlite_write_lock if engine.dialect.name == "sqlite" else contextlib.nullcontext()


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create tables and opportunistically enable TimescaleDB.

    Uses create_all for Phase 1 convenience; Alembic migrations in
    backend/alembic are the source of truth going forward.
    """
    from app import models  # noqa: F401  (register models on Base.metadata)
    from sqlalchemy import text

    # Each opportunistic step below gets its OWN transaction. A failed
    # statement (e.g. CREATE EXTENSION on plain Postgres, or
    # create_hypertable on non-Timescale Postgres) must only roll back
    # that step - sharing one transaction across steps would let a later
    # failure's rollback silently wipe out the create_all DDL that
    # already succeeded earlier in the same transaction.
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
    except Exception:
        pass  # Plain PostgreSQL without Timescale - fine, regular tables still work.

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    for table, time_column in (
        ("market_quotes", "observed_at"),
        ("collector_logs", "started_at"),
        ("system_health", "recorded_at"),
    ):
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "SELECT create_hypertable(:table, :column, if_not_exists => TRUE, "
                        "migrate_data => TRUE)"
                    ),
                    {"table": table, "column": time_column},
                )
        except Exception:
            pass
