from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.manager import collector_manager, is_active_session
from app.database.session import get_db
from app.models.market import Instrument
from app.schemas.market import InstrumentOut, MarketStatusOut, QuoteOut, SourceHealthOut
from app.services.market_service import get_latest_quotes

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/status", response_model=MarketStatusOut)
async def market_status() -> MarketStatusOut:
    now = datetime.now(timezone.utc)
    sources = [
        SourceHealthOut(
            source_id=s["source_id"],
            name=s["name"],
            status=s["status"],
            last_success_at=s["last_success_at"],
            last_error=s["last_error"],
            last_error_at=s["last_error_at"],
            consecutive_failures=s["consecutive_failures"],
            latency_ms=s["latency_ms"],
            stale_seconds=(now - s["last_success_at"]).total_seconds() if s["last_success_at"] else None,
        )
        for s in collector_manager.health_snapshot()
    ]
    return MarketStatusOut(is_active_session=is_active_session(now), server_time=now, sources=sources)


@router.get("/quotes", response_model=list[QuoteOut])
async def latest_quotes(source_id: str | None = None, db: AsyncSession = Depends(get_db)) -> list[QuoteOut]:
    rows = await get_latest_quotes(db, source_id=source_id)
    return [
        QuoteOut(
            source_id=row.source_id,
            source_symbol=row.source_symbol,
            observed_at=row.observed_at,
            last_price=float(row.last_price) if row.last_price is not None else None,
            close_price=float(row.close_price) if row.close_price is not None else None,
            price_change=float(row.price_change) if row.price_change is not None else None,
            price_change_percent=float(row.price_change_percent) if row.price_change_percent is not None else None,
            volume=float(row.volume) if row.volume is not None else None,
            value=float(row.value) if row.value is not None else None,
            transaction_count=row.transaction_count,
            is_stale=row.is_stale,
            raw=row.raw,
        )
        for row in rows
    ]


@router.get("/instruments", response_model=list[InstrumentOut])
async def instruments(db: AsyncSession = Depends(get_db)) -> list[InstrumentOut]:
    result = await db.execute(select(Instrument).order_by(Instrument.symbol))
    return list(result.scalars().all())
