from datetime import datetime, timezone

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.manager import collector_manager
from app.core.logging import get_logger
from app.database.session import get_db
from app.services.market_service import get_latest_quotes
from app.websocket.manager import manager as ws_manager

router = APIRouter()
logger = get_logger(__name__)


@router.websocket("/ws/market")
async def market_ws(websocket: WebSocket, db: AsyncSession = Depends(get_db)) -> None:
    # Uses the same `get_db` dependency as every REST route (rather than
    # opening its own SessionLocal directly) so it honors dependency
    # overrides like the REST routes do - both for tests and for anything
    # that needs to swap the DB session per-request in the future.
    await ws_manager.connect(websocket)
    try:
        rows = await get_latest_quotes(db)
        await ws_manager.send_to(
            websocket,
            {
                "type": "snapshot",
                "server_time": datetime.now(timezone.utc).isoformat(),
                "sources": collector_manager.health_snapshot(),
                # Same field set as the "quotes" delta message broadcast by
                # collector_manager after each cycle (see asdict(quote)
                # there) - a symbol that hasn't changed since this snapshot
                # was taken would otherwise never get a delta update and
                # would be stuck missing whatever fields this list omits
                # (found via TSETMC_FREE_POWER_OVERVIEW's value/
                # transaction_count coming back null on first load).
                "quotes": [
                    {
                        "source_id": r.source_id,
                        "source_symbol": r.source_symbol,
                        "observed_at": r.observed_at,
                        "last_price": float(r.last_price) if r.last_price is not None else None,
                        "close_price": float(r.close_price) if r.close_price is not None else None,
                        "price_change": float(r.price_change) if r.price_change is not None else None,
                        "price_change_percent": float(r.price_change_percent)
                        if r.price_change_percent is not None
                        else None,
                        "volume": float(r.volume) if r.volume is not None else None,
                        "value": float(r.value) if r.value is not None else None,
                        "transaction_count": r.transaction_count,
                        "raw": r.raw,
                    }
                    for r in rows
                ],
            },
        )

        while True:
            # Clients don't need to send anything; this just detects disconnects
            # and answers heartbeats so the connection doesn't idle-timeout.
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        # Client went away while the snapshot was being sent: send_to has
        # already logged and dropped it, and Starlette then raises
        # RuntimeError (not WebSocketDisconnect) from receive_text().
        pass
    finally:
        await ws_manager.disconnect(websocket)
