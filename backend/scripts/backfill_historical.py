"""Manually run the historical backfill (see app/services/historical_ingestion.py).

Usage (from backend/, with the venv active):
    python scripts/backfill_historical.py [start_jalali_year] [end_jalali_year]

Safe to re-run - it upserts by (source, symbol, month), never duplicates.
The app also re-runs this automatically on every startup (see
app/main.py), so running it by hand is only needed to backfill a specific
year range without restarting the app.
"""

import asyncio
import sys

import httpx

from app.core.config import get_settings
from app.database.session import SessionLocal
from app.services.historical_ingestion import EARLIEST_JALALI_YEAR, backfill_iee_monthly_prices


async def main() -> None:
    settings = get_settings()
    start_year = int(sys.argv[1]) if len(sys.argv) > 1 else EARLIEST_JALALI_YEAR
    end_year = int(sys.argv[2]) if len(sys.argv) > 2 else None

    async with httpx.AsyncClient() as client, SessionLocal() as session:
        written = await backfill_iee_monthly_prices(
            session, client, settings.IEE_NEW_BASE_URL, start_year, end_year
        )
    print(f"Backfilled {written} monthly quotes.")


if __name__ == "__main__":
    asyncio.run(main())
