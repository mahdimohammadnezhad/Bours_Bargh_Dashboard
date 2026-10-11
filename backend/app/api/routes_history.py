from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.schemas.market import PriceHistoryOut, PriceHistoryPoint
from app.services.market_service import get_price_history

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/prices", response_model=PriceHistoryOut)
async def price_history(
    source_id: str = Query(...),
    symbol: str = Query(..., description="source-specific symbol, as returned by /api/market/quotes"),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PriceHistoryOut:
    end = end or datetime.now(timezone.utc)
    start = start or (end - timedelta(days=7))

    rows = await get_price_history(db, source_id, symbol, start, end)
    return PriceHistoryOut(
        source_id=source_id,
        source_symbol=symbol,
        points=[
            PriceHistoryPoint(
                observed_at=row.observed_at,
                last_price=float(row.last_price) if row.last_price is not None else None,
                volume=float(row.volume) if row.volume is not None else None,
                raw=row.raw,
            )
            for row in rows
        ],
    )
