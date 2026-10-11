from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.collectors.base import CycleResult, NormalizedQuote
from app.collectors.tsetmc_collector import TSETMCCollector
from app.models.market import MarketQuote
from app.services.market_service import ensure_data_source, get_latest_quotes, record_cycle, upsert_quote


@pytest.mark.asyncio
async def test_record_cycle_writes_a_real_row_via_sqlite_upsert(db_session):
    # Regression test for a real bug: record_cycle used to build its upsert
    # with sqlalchemy.dialects.postgresql.insert(...).on_conflict_do_update
    # unconditionally, which raised `no such column: uq_quote_tick` the
    # first time this ran against SQLite (exactly what local dev/testing
    # uses - see docs/TROUBLESHOOTING.md). This exercises the fix for real,
    # not through a mock, so this dialect mismatch can't silently return.
    collector = TSETMCCollector()
    await ensure_data_source(db_session, collector)

    quote = NormalizedQuote(
        source_id="tsetmc",
        source_symbol="TEST_SYMBOL",
        observed_at=datetime.now(timezone.utc),
        value=123.0,
        transaction_count=5,
    )
    result = CycleResult(status="success", quotes=[quote])

    written, changed = await record_cycle(db_session, collector, result)
    assert len(written) == 1
    assert changed is True

    rows = (await db_session.execute(select(MarketQuote).where(MarketQuote.source_symbol == "TEST_SYMBOL"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].value == pytest.approx(123.0)
    assert rows[0].transaction_count == 5


@pytest.mark.asyncio
async def test_record_cycle_upserts_not_duplicates_on_same_key(db_session):
    collector = TSETMCCollector()
    await ensure_data_source(db_session, collector)

    observed_at = datetime.now(timezone.utc)
    first = NormalizedQuote(
        source_id="tsetmc", source_symbol="TEST_UPSERT", observed_at=observed_at, value=100.0, transaction_count=1
    )
    await record_cycle(db_session, collector, CycleResult(status="success", quotes=[first]))

    # Same (source_id, source_symbol, observed_at) key, different values -
    # must UPDATE the existing row, not insert a second one.
    second = NormalizedQuote(
        source_id="tsetmc", source_symbol="TEST_UPSERT", observed_at=observed_at, value=200.0, transaction_count=2
    )
    await record_cycle(db_session, collector, CycleResult(status="success", quotes=[second]))

    rows = (await db_session.execute(select(MarketQuote).where(MarketQuote.source_symbol == "TEST_UPSERT"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].value == pytest.approx(200.0)
    assert rows[0].transaction_count == 2


@pytest.mark.asyncio
async def test_timestamps_read_back_as_aware_utc_on_sqlite(db_session):
    # Regression: SQLite returned naive datetimes, serialized without an
    # offset, which browsers parse as local time (3.5h off in Tehran).
    tehran = timezone(timedelta(hours=3, minutes=30))
    when = datetime(2026, 10, 11, 10, 54, 3, tzinfo=tehran)
    await upsert_quote(db_session, NormalizedQuote(source_id="iee_new", source_symbol="TZ", observed_at=when, last_price=1.0))
    await db_session.commit()
    db_session.expire_all()

    row = next(r for r in await get_latest_quotes(db_session, source_id="iee_new") if r.source_symbol == "TZ")
    assert row.observed_at.utcoffset() == timedelta(0)
    assert row.observed_at == when  # same instant, normalized to UTC


async def _rows_for(db_session, symbol: str) -> list[MarketQuote]:
    return list(
        (await db_session.execute(select(MarketQuote).where(MarketQuote.source_symbol == symbol))).scalars().all()
    )


@pytest.mark.asyncio
async def test_record_cycle_skips_unchanged_reobservation(db_session):
    # Regression test for real table bloat: IEE's board re-lists ~440
    # mostly-idle contracts every 5s cycle, and each was stored again as a
    # new row under a fresh observed_at even when nothing had changed.
    collector = TSETMCCollector()
    await ensure_data_source(db_session, collector)
    t0 = datetime.now(timezone.utc)

    first = NormalizedQuote(source_id="tsetmc", source_symbol="IDLE", observed_at=t0, last_price=10.0, volume=0.0)
    written, changed = await record_cycle(db_session, collector, CycleResult(status="success", quotes=[first]))
    assert (len(written), changed) == (1, True)

    again = NormalizedQuote(
        source_id="tsetmc", source_symbol="IDLE", observed_at=t0 + timedelta(seconds=5), last_price=10.0, volume=0.0
    )
    written, changed = await record_cycle(db_session, collector, CycleResult(status="success", quotes=[again]))
    assert (len(written), changed) == (0, False)
    assert len(await _rows_for(db_session, "IDLE")) == 1


@pytest.mark.asyncio
async def test_record_cycle_writes_only_the_symbols_that_changed(db_session):
    collector = TSETMCCollector()
    await ensure_data_source(db_session, collector)
    t0 = datetime.now(timezone.utc)
    t1 = t0 + timedelta(seconds=5)

    await record_cycle(
        db_session,
        collector,
        CycleResult(
            status="success",
            quotes=[
                NormalizedQuote(source_id="tsetmc", source_symbol="STEADY", observed_at=t0, last_price=1.0),
                NormalizedQuote(source_id="tsetmc", source_symbol="MOVING", observed_at=t0, last_price=1.0),
            ],
        ),
    )
    written, changed = await record_cycle(
        db_session,
        collector,
        CycleResult(
            status="success",
            quotes=[
                NormalizedQuote(source_id="tsetmc", source_symbol="STEADY", observed_at=t1, last_price=1.0),
                NormalizedQuote(source_id="tsetmc", source_symbol="MOVING", observed_at=t1, last_price=2.0),
            ],
        ),
    )

    assert changed is True
    assert [q.source_symbol for q in written] == ["MOVING"]
    assert len(await _rows_for(db_session, "STEADY")) == 1
    assert len(await _rows_for(db_session, "MOVING")) == 2


@pytest.mark.asyncio
async def test_failed_commit_does_not_mark_quotes_as_persisted(db_session, monkeypatch):
    # Otherwise the next cycle would skip these as "already stored" and the
    # data would be missing until the values happened to change.
    collector = TSETMCCollector()
    await ensure_data_source(db_session, collector)
    quote = NormalizedQuote(source_id="tsetmc", source_symbol="X", observed_at=datetime.now(timezone.utc), last_price=1.0)

    async def _failing_commit() -> None:
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(db_session, "commit", _failing_commit)
    with pytest.raises(RuntimeError):
        await record_cycle(db_session, collector, CycleResult(status="success", quotes=[quote]))

    assert collector.state.last_persisted == {}


@pytest.mark.asyncio
async def test_record_cycle_keeps_identical_older_dated_history_rows(db_session):
    # TSETMC's daily history arrives under the same symbol as the live
    # quote; two quiet days can carry identical numbers but are still two
    # distinct data points, so dedup must not collapse them.
    collector = TSETMCCollector()
    await ensure_data_source(db_session, collector)
    now = datetime.now(timezone.utc)
    day1 = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=2)
    day2 = day1 + timedelta(days=1)

    written, _ = await record_cycle(
        db_session,
        collector,
        CycleResult(
            status="success",
            quotes=[
                NormalizedQuote(source_id="tsetmc", source_symbol="CONTRACT", observed_at=now, last_price=5.0),
                NormalizedQuote(source_id="tsetmc", source_symbol="CONTRACT", observed_at=day2, last_price=5.0),
                NormalizedQuote(source_id="tsetmc", source_symbol="CONTRACT", observed_at=day1, last_price=5.0),
            ],
        ),
    )

    assert len(written) == 3
    assert len(await _rows_for(db_session, "CONTRACT")) == 3


@pytest.mark.asyncio
async def test_get_latest_quotes_does_not_starve_a_slow_ticking_symbol(db_session):
    # Regression test for a real bug: get_latest_quotes used to take the
    # 500 globally-most-recent rows and dedup those in Python. A symbol
    # that updates rarely (like the monthly historical backfill) got
    # silently excluded entirely once a busier symbol produced 500+ more
    # recent rows than it - even though both had real data in the table.
    # This reproduces that exact shape at a smaller scale (5 vs 1) and
    # asserts the slow symbol still comes back.
    now = datetime.now(timezone.utc)

    for i in range(5):
        await upsert_quote(
            db_session,
            NormalizedQuote(
                source_id="iee_new",
                source_symbol="BUSY_SYMBOL",
                observed_at=now.replace(microsecond=i),
                last_price=100.0 + i,
            ),
        )
    # One much older, slow-ticking symbol - would be starved out by a
    # "top N globally" query once N < the busy symbol's row count.
    await upsert_quote(
        db_session,
        NormalizedQuote(
            source_id="iee_new",
            source_symbol="SLOW_MONTHLY_SYMBOL",
            observed_at=now.replace(year=now.year - 1),
            last_price=42.0,
        ),
    )
    await db_session.commit()

    rows = await get_latest_quotes(db_session, source_id="iee_new")
    by_symbol = {r.source_symbol: r for r in rows}

    assert "SLOW_MONTHLY_SYMBOL" in by_symbol
    assert float(by_symbol["SLOW_MONTHLY_SYMBOL"].last_price) == 42.0
    assert float(by_symbol["BUSY_SYMBOL"].last_price) == 104.0  # the latest of the 5, not an older one
