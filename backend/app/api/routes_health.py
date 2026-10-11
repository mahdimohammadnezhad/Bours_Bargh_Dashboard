from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.manager import collector_manager
from app.database.session import get_db
from app.models.market import CollectorLog
from app.schemas.market import CollectorLogOut, SourceHealthOut

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/sources", response_model=list[SourceHealthOut])
async def source_health() -> list[SourceHealthOut]:
    now = datetime.now(timezone.utc)
    out: list[SourceHealthOut] = []
    for snap in collector_manager.health_snapshot():
        last_success = snap["last_success_at"]
        stale_seconds = (now - last_success).total_seconds() if last_success else None
        out.append(
            SourceHealthOut(
                source_id=snap["source_id"],
                name=snap["name"],
                status=snap["status"],
                last_success_at=last_success,
                last_error=snap["last_error"],
                last_error_at=snap["last_error_at"],
                consecutive_failures=snap["consecutive_failures"],
                latency_ms=snap["latency_ms"],
                stale_seconds=stale_seconds,
            )
        )
    return out


@router.get("/logs", response_model=list[CollectorLogOut])
async def collector_logs(
    source_id: str | None = None, limit: int = 50, db: AsyncSession = Depends(get_db)
) -> list[CollectorLog]:
    stmt = select(CollectorLog).order_by(CollectorLog.started_at.desc()).limit(min(limit, 200))
    if source_id:
        stmt = stmt.where(CollectorLog.source_id == source_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/live")
async def liveness() -> dict:
    return {"status": "ok", "server_time": datetime.now(timezone.utc).isoformat()}
