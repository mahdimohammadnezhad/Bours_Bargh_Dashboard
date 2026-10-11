from datetime import date, datetime, timezone

from sqlalchemy import JSON, BigInteger, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.database.session import Base

# SQLite only auto-populates an integer primary key when the column's DDL
# affinity is the literal word "INTEGER" (its rowid alias) - a plain
# BigInteger column renders as "BIGINT" there and never gets a value
# assigned automatically, causing NOT NULL failures on insert. Postgres
# (production) has no such quirk and gets the full BIGINT/BIGSERIAL range
# either way, so this variant only changes behavior on SQLite.
_BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class UTCDateTime(TypeDecorator):
    """DateTime(timezone=True) that always round-trips as aware UTC.

    PostgreSQL's timestamptz already does. SQLite stores no offset and hands
    back naive datetimes, which the API serialized without one - and
    browsers parse an offset-less timestamp as *local* time, so every
    DB-sourced time on the dashboard was shifted by the viewer's UTC offset
    (3.5h in Tehran) while live WebSocket pushes were correct. Same DDL as
    DateTime(timezone=True), so no migration is involved.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001, ANN201, ARG002
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):  # noqa: ANN001, ANN201, ARG002
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # 'tsetmc' | 'iee_new' | 'iee_old'
    name: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), default="unknown")  # healthy|degraded|down|not_configured
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(_BigIntPK, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    market_segment: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    source_links: Mapped[list["SourceInstrument"]] = relationship(back_populates="instrument")


class SourceInstrument(Base):
    """Maps a source-specific identifier onto a canonical instrument."""

    __tablename__ = "source_instruments"
    __table_args__ = (UniqueConstraint("source_id", "source_symbol", name="uq_source_symbol"),)

    id: Mapped[int] = mapped_column(_BigIntPK, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    source_symbol: Mapped[str] = mapped_column(String(128))

    instrument: Mapped[Instrument] = relationship(back_populates="source_links")


class MarketQuote(Base):
    """Append-only time-series fact table. One row per (source, symbol, observed_at)."""

    __tablename__ = "market_quotes"

    id: Mapped[int] = mapped_column(_BigIntPK, primary_key=True, autoincrement=True)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    source_symbol: Mapped[str] = mapped_column(String(128), index=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), nullable=True)

    last_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    close_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    price_change: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    price_change_percent: Mapped[float | None] = mapped_column(Numeric(9, 4), nullable=True)
    volume: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    value: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    transaction_count: Mapped[int | None] = mapped_column(nullable=True)

    is_stale: Mapped[bool] = mapped_column(default=False)
    raw_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # The collector's raw per-quote context (contract name, market-state
    # text, etc.) - fields that don't have their own column but the
    # frontend still needs (e.g. "برترین قیمت تقاضا" needs the contract
    # title, not just its symbol). Stored inline rather than via raw_ref's
    # file/object-storage indirection (brief §41) since payloads here are
    # small (a few hundred bytes) - revisit if that changes.
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("source_id", "source_symbol", "observed_at", name="uq_quote_tick"),
        # market_service.get_latest_quotes() partitions by (source_id,
        # source_symbol) and orders each partition by observed_at DESC.
        # The unique constraint above covers these columns but in plain
        # ascending order tied to equality on all three, which still left
        # SQLite building a temp sort per partition once the table grew
        # past ~700k rows in practice (a multi-hour continuous local test
        # run, not exaggerated for effect) - descending order on the
        # trailing column matches that access pattern directly. Column
        # names are passed as strings/text() (resolved against the table
        # being built), not as attribute references, because __table_args__
        # would otherwise need to forward-reference columns defined above -
        # this ordering (columns first, __table_args__ last) is only for
        # readability, not a requirement.
        Index("ix_quote_symbol_observed_desc", "source_id", "source_symbol", text("observed_at DESC")),
    )


class CollectorLog(Base):
    __tablename__ = "collector_logs"

    id: Mapped[int] = mapped_column(_BigIntPK, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(32))  # success|error|skipped|not_configured
    http_status: Mapped[int | None] = mapped_column(nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(nullable=True)
    records_fetched: Mapped[int] = mapped_column(default=0)
    records_inserted: Mapped[int] = mapped_column(default=0)
    records_skipped: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class WeatherDaily(Base):
    """Daily temperature per location, observed or forecast.

    `location` is an aggregate such as "IR_POP_WEIGHTED" (population-weighted
    mean of several Iranian cities - see app/services/weather.py); the
    per-city values it was built from are kept in `raw`. A forecast row is
    overwritten by the observed value once that day has passed.
    """

    __tablename__ = "weather_daily"
    __table_args__ = (UniqueConstraint("location", "day", name="uq_weather_location_day"),)

    id: Mapped[int] = mapped_column(_BigIntPK, primary_key=True, autoincrement=True)
    location: Mapped[str] = mapped_column(String(32), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    t_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    t_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    t_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_forecast: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String(64))
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())


class SystemHealth(Base):
    __tablename__ = "system_health"

    id: Mapped[int] = mapped_column(_BigIntPK, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    status: Mapped[str] = mapped_column(String(32))
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(nullable=True)
    stale_seconds: Mapped[float | None] = mapped_column(nullable=True)
