import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import BaseCollector, CycleResult, NormalizedQuote
from app.core.config import get_settings
from app.models.market import CollectorLog, DataSource, MarketQuote

settings = get_settings()

# Postgres (production) and SQLite (tests, quick local dev - see
# docs/TROUBLESHOOTING.md) need different `insert(...).on_conflict_do_update`
# constructs: only the dialect-specific Insert subclass returned by each of
# these has that method at all. `index_elements` (actual column names,
# matching MarketQuote's `uq_quote_tick` unique constraint below) rather than
# `constraint=<name>` is used because it's the one spelling both dialects
# accept - SQLite has no notion of referencing a unique constraint by name in
# an ON CONFLICT clause.
_DIALECT_INSERT = {"postgresql": pg_insert, "sqlite": sqlite_insert}


def quote_fingerprint(quote: NormalizedQuote) -> str:
    """Everything about a quote except when it was observed. `raw` is
    included because some state lives only there (e.g. the overview's
    open/closed market text can flip while its numbers stay put)."""
    payload = (
        quote.last_price,
        quote.close_price,
        quote.price_change,
        quote.price_change_percent,
        quote.volume,
        quote.value,
        quote.transaction_count,
        quote.raw,
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def ensure_data_source(session: AsyncSession, collector: BaseCollector) -> None:
    existing = await session.get(DataSource, collector.source_id)
    if existing is None:
        session.add(
            DataSource(
                id=collector.source_id,
                name=collector.name,
                base_url=collector.base_url,
                status=collector.state.status,
            )
        )
        await session.commit()


async def upsert_quote(session: AsyncSession, quote: NormalizedQuote) -> None:
    """Insert one quote, or update it in place if (source_id, source_symbol,
    observed_at) already exists - shared by the real-time collector cycle
    (`record_cycle` below) and the historical backfill pipeline
    (`historical_ingestion.py`), so both dedup/upsert the exact same way.

    Does not commit - callers batch their own commits.
    """
    dialect_name = session.bind.dialect.name if session.bind is not None else "postgresql"
    insert_ = _DIALECT_INSERT.get(dialect_name, pg_insert)

    stmt = (
        insert_(MarketQuote)
        .values(
            observed_at=quote.observed_at,
            source_id=quote.source_id,
            source_symbol=quote.source_symbol,
            last_price=quote.last_price,
            close_price=quote.close_price,
            price_change=quote.price_change,
            price_change_percent=quote.price_change_percent,
            volume=quote.volume,
            value=quote.value,
            transaction_count=quote.transaction_count,
            is_stale=False,
            raw=quote.raw,
        )
        .on_conflict_do_update(
            index_elements=["source_id", "source_symbol", "observed_at"],
            set_={
                "last_price": quote.last_price,
                "close_price": quote.close_price,
                "price_change": quote.price_change,
                "price_change_percent": quote.price_change_percent,
                "volume": quote.volume,
                "value": quote.value,
                "transaction_count": quote.transaction_count,
                "is_stale": False,
                "raw": quote.raw,
            },
        )
    )
    await session.execute(stmt)


async def record_cycle(
    session: AsyncSession, collector: BaseCollector, result: CycleResult
) -> tuple[list[NormalizedQuote], bool]:
    """Persist one collector cycle: log entry, source health, and any new/changed quotes.

    Dedup is per symbol: a quote that is newer than the last one persisted
    for its symbol but otherwise identical is a re-observation, not new
    data, and is skipped. This matters in practice - IEE's trade board
    lists ~440 contracts per cycle of which only a handful trade on a
    given day, and storing every one every 5s grew the table by ~300k
    rows/hour of duplicates. Older-dated quotes (daily history) are keyed
    rows and always upserted.

    Returns (quotes_written, changed) so the caller broadcasts only what
    actually changed over the WebSocket.
    """
    started = datetime.now(timezone.utc)
    quotes_written: list[NormalizedQuote] = []
    # Applied to collector.state only after the commit succeeds - otherwise a
    # failed commit would leave these marked as stored and skipped next cycle.
    newly_persisted: dict[str, tuple[datetime, str]] = {}

    if result.status == "success" and result.quotes:
        persisted = collector.state.last_persisted
        for quote in result.quotes:
            fingerprint = quote_fingerprint(quote)
            previous = newly_persisted.get(quote.source_symbol) or persisted.get(quote.source_symbol)
            if previous is not None and quote.observed_at > previous[0] and fingerprint == previous[1]:
                continue
            await upsert_quote(session, quote)
            quotes_written.append(quote)
            if previous is None or quote.observed_at >= previous[0]:
                newly_persisted[quote.source_symbol] = (quote.observed_at, fingerprint)

    changed = bool(quotes_written)

    source = await session.get(DataSource, collector.source_id)
    if source is not None:
        source.status = collector.state.status
        source.last_success_at = collector.state.last_success_at
        source.last_error = collector.state.last_error
        source.last_error_at = collector.state.last_error_at
        source.consecutive_failures = collector.state.consecutive_failures

    session.add(
        CollectorLog(
            source_id=collector.source_id,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            status=result.status,
            http_status=result.http_status,
            latency_ms=result.latency_ms,
            records_fetched=len(result.quotes),
            records_inserted=len(quotes_written),
            records_skipped=len(result.quotes) - len(quotes_written),
            error_message=result.error_message,
        )
    )
    await session.commit()
    collector.state.last_persisted.update(newly_persisted)

    return quotes_written, changed


async def get_latest_quotes(session: AsyncSession, source_id: str | None = None) -> list[MarketQuote]:
    """One row per (source_id, source_symbol): its most recent observation.

    Computed per group rather than "take the N most recent rows overall,
    then dedup in Python" - the latter silently drops any symbol that ticks
    less often than the busiest ones once distinct symbols outnumber N
    (e.g. IEE's ~450 per-cycle contract quotes crowded out the once-a-month
    historical backfill rows entirely, even though both exist in the
    table).

    MAX(observed_at) per group, joined back on the unique key, rather than
    ROW_NUMBER() over the whole table: the GROUP BY is answered from the
    (source_id, source_symbol, observed_at) index alone, and only the ~600
    winning rows are then read in full. The window version read every row
    including its raw JSON - ~1.1s per call on a 140k-row SQLite table vs
    ~0.14s, and this runs on every page load and WebSocket connect.
    """
    latest_key = select(
        MarketQuote.source_id,
        MarketQuote.source_symbol,
        func.max(MarketQuote.observed_at).label("observed_at"),
    ).group_by(MarketQuote.source_id, MarketQuote.source_symbol)
    if source_id:
        latest_key = latest_key.where(MarketQuote.source_id == source_id)
    latest_key = latest_key.subquery()

    stmt = select(MarketQuote).join(
        latest_key,
        and_(
            MarketQuote.source_id == latest_key.c.source_id,
            MarketQuote.source_symbol == latest_key.c.source_symbol,
            MarketQuote.observed_at == latest_key.c.observed_at,
        ),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_price_history(
    session: AsyncSession,
    source_id: str,
    source_symbol: str,
    start: datetime,
    end: datetime,
) -> list[MarketQuote]:
    stmt = (
        select(MarketQuote)
        .where(
            MarketQuote.source_id == source_id,
            MarketQuote.source_symbol == source_symbol,
            MarketQuote.observed_at >= start,
            MarketQuote.observed_at <= end,
        )
        .order_by(MarketQuote.observed_at.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
