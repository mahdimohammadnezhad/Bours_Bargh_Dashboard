"""Historical backfill for IEE's monthly average price report, and for the
Free Power derivative market's full daily statistics history.

VERIFIED against a live response - see docs/DATA_SOURCES.md. Found by
reading the request-building code in newsite.iee.ir's JS bundle: the
Monthly Price Report component builds its request body from moment-jalaali
state (`{Year: v, Months: [w]}` where v/w are the current Jalali
year/month), then POSTs it - confirming the report is indexed by the
Iranian (Jalali/Shamsi) calendar, not Gregorian. The year-picker in that
same component generates years from 1402 up to the current Jalali year,
so 1402 is treated as the earliest available year rather than guessed.

    POST {base}/Report/GetPowerMarketMonthlyPrice
    body: {"Year": <jalali year>, "Months": [1, 2, ..., 12]}
    -> {"results": [{"year": 1405, "month": 5,
                      "firstSignboardBaseLoadMidPrice": "3459",
                      "greenSignboardBaseLoadMidPrice": "134811",
                      "freeSignboardBaseLoadMidPrice": "118933",
                      ...}, ...],
        "isSuccess": true, ...}

Confirmed live on 2026-08-30: querying the current in-progress Jalali
month (1405/6) returned an empty result - no average published yet for a
month that hasn't closed - while the prior completed month (1405/5)
returned real data. So this endpoint only ever contains completed months,
which is exactly what a monthly-average report should do; no special
"skip the current month" logic is needed here, the upstream API already
omits it.

"firstSignboard"/"greenSignboard"/"freeSignboard" correspond to the same
three sub-markets (Power/Green/Free) tracked elsewhere in
iee_new_collector.py. Only the "BaseLoad...MidPrice" field was populated
in the one response captured (Low/Mid/High-load and Max-price variants
were empty strings or null) - this ingests only that field per segment,
consistent with the "base load" contracts already seen throughout this
project (e.g. TSETMC's "بارپايه" contracts). If a future response has the
other load types populated too, they are simply not captured yet - not
confirmed absent.

---

Second endpoint: the Free Power derivative market's full statistics
history (per contract, per day) - this is the actual "کل تایم سریز"
(complete time series) requested for the dashboard, found by driving the
newsite.iee.ir Statistics page itself with Playwright + network
interception (select بازار برق > برق آزاد > مشتقه برق آزاد, tab آمار):

    GET {base}/PowerMarket/GetDerivativeFreePowerMarketStatistics
        ?Lang=fa&start=0&PageNumber=1&PageSize=<n>
        &FromDate=<jalali Y/M/D>&ToDate=<jalali Y/M/D>
    -> {"results": [{"date": "1405/06/14", "energySymbol": "DDP00PFBEXW050621",
                      "contract": "بارپايه هفتگي 14050621",
                      "avgPrice": "59000", "maxPrice": "59,000",
                      "minPrice": "59,000", "tradeNo": "2",
                      "tradeVolumeTooltip": "300", "closingPrice": "59,000",
                      "tradeValue": "2,973,600,000",
                      "kiloWattHours": "50,400"}, ...],
        "pagedMetaData": [{"totalCount": 261, ...}], "isSuccess": true}

Verified live on 2026-09-05: requesting FromDate=1390/01/01 (IEE's own
founding year, per the Statistics page's own footer text) through today
returned exactly 261 rows starting at 1404/01/27 - i.e. the endpoint
itself has no data before that date for this specific market/sub-market
combination, this project didn't truncate anything.

That single whole-history request stopped working by 2026-10-11: the same
call took ~32s and came back HTTP 400 `isFailed` ("unknown error"), while
one-Jalali-year windows returned in 4-7s each. So the backfill now walks
the history one Jalali year per request.

`energySymbol` here is the *same* identifier TSETMC's own Energy contracts
expose (see tsetmc_collector.py) - confirmed by an exact match
("DDP00PFBEXW050621") for the same contract on the same day from both
sites independently. This collector uses that symbol directly (not
prefixed per-source) specifically so `market_quotes` rows from `tsetmc`
and `iee_new` for the same instrument land under the same `source_symbol`
and can be compared/overlaid, differing only by `source_id`.
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jdatetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import NormalizedQuote
from app.core.logging import get_logger
from app.database.session import db_write_lock
from app.services.market_service import upsert_quote

logger = get_logger(__name__)

SOURCE_ID = "iee_new"
# IEE's WAF answers request bursts with 403 (seen 2026-10-11: the startup
# backfill's back-to-back calls plus the live collector's cycle lost a
# whole year of the monthly report). Each backfill request waits this long
# first, which also lets the collector's own first cycle go out ahead.
IEE_REQUEST_SPACING_SECONDS = 2.0
MONTHLY_PRICE_PATH = "/Report/GetPowerMarketMonthlyPrice"
EARLIEST_JALALI_YEAR = 1402

DERIVATIVE_FREE_STATS_PATH = "/PowerMarket/GetDerivativeFreePowerMarketStatistics"
# Confirmed live 2026-09-05 (full-range query from 1390/01/01) and again
# 2026-10-11 (1403 window empty): no data before 1404/01/27 for this market.
DERIVATIVE_FREE_STATS_EARLIEST_JALALI_YEAR = 1404

# Main (regulated) power market's per-contract daily statistics - the long
# daily price history the temperature/season forecast is trained on. The
# path's "Deriative" spelling is IEE's own (from its frontend bundle,
# verified live 2026-10-11). Same paged params/row shape as the Free-market
# report; history starts in 1398 (148 rows that year, 5,170 through 1405/07).
POWER_DERIVATIVE_STATS_PATH = "/PowerMarket/GetDeriativePowerMarketStatistics"
POWER_STATS_EARLIEST_JALALI_YEAR = 1398
# One row per trading day: volume-weighted average price of all base-load
# ("بارپايه") contracts traded that day, in Rials/kWh. Base load is by far
# the most traded product (3,300 of 5,170 rows) and the only one present
# every year, so it gives a consistent series; peak/mid/low-load contracts
# price differently and would make a daily mix-dependent average.
POWER_BASELOAD_SYMBOL = "IEE_POWER_BASELOAD_DAILY"
_BASELOAD_PREFIX = "بارپايه"

# (JSON field name, canonical source_symbol) - mirrors the Day-level
# symbols already used by iee_new_collector.py, at monthly granularity.
_SEGMENT_FIELDS = [
    ("firstSignboardBaseLoadMidPrice", "IEE_POWER_BASE_MONTHLY"),
    ("greenSignboardBaseLoadMidPrice", "IEE_GREEN_BASE_MONTHLY"),
    ("freeSignboardBaseLoadMidPrice", "IEE_FREE_BASE_MONTHLY"),
]


def _parse_comma_number(value: Any) -> float | None:
    """Same comma-grouped-string handling as iee_new_collector.py."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[,\s]", "", value)
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _last_day_of_jalali_month_utc(jalali_year: int, jalali_month: int) -> datetime:
    """The report has no day-level granularity - each row is one completed
    Jalali month's average. Stamping `observed_at` as that month's last
    day (not e.g. the 1st) sorts it correctly alongside daily/live data
    and reads naturally as "as of end of month"."""
    if jalali_month == 12:
        next_month_first = jdatetime.date(jalali_year + 1, 1, 1)
    else:
        next_month_first = jdatetime.date(jalali_year, jalali_month + 1, 1)
    last_day = (next_month_first - timedelta(days=1)).togregorian()
    return datetime(last_day.year, last_day.month, last_day.day, tzinfo=timezone.utc)


async def fetch_monthly_prices(client: httpx.AsyncClient, base_url: str, jalali_year: int) -> list[dict]:
    response = await client.post(
        f"{base_url}{MONTHLY_PRICE_PATH}",
        json={"Year": jalali_year, "Months": list(range(1, 13))},
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ElectricityMarketDashboard/1.0; +data-collector)",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not body.get("isSuccess"):
        return []
    results = body.get("results")
    return results if isinstance(results, list) else []


def parse_monthly_prices(rows: list[dict]) -> list[NormalizedQuote]:
    quotes: list[NormalizedQuote] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        year, month = row.get("year"), row.get("month")
        if not isinstance(year, int) or not isinstance(month, int):
            continue
        try:
            observed_at = _last_day_of_jalali_month_utc(year, month)
        except ValueError as exc:
            logger.warning("historical_ingestion: skipping invalid Jalali date %s/%s: %s", year, month, exc)
            continue

        for field, symbol in _SEGMENT_FIELDS:
            price = _parse_comma_number(row.get(field))
            # "0" means no average was published for that month/segment
            # (51 of 126 rows, e.g. all of early 1402) - not a price of zero.
            if price is None or price <= 0:
                continue
            quotes.append(
                NormalizedQuote(
                    source_id=SOURCE_ID,
                    source_symbol=symbol,
                    observed_at=observed_at,
                    last_price=price,
                    raw=row,
                )
            )
    return quotes


async def backfill_iee_monthly_prices(
    session: AsyncSession,
    client: httpx.AsyncClient,
    base_url: str,
    start_jalali_year: int = EARLIEST_JALALI_YEAR,
    end_jalali_year: int | None = None,
) -> int:
    """Backfill IEE's monthly average base-load price for Power/Green/Free,
    one year at a time (the report accepts up to 12 months per call).
    Idempotent - re-running re-upserts the same (source, symbol, month) key
    (via market_service.upsert_quote) rather than duplicating rows, so this
    is safe to re-run on every app startup, not just once.
    """
    end_jalali_year = end_jalali_year or jdatetime.date.today().year
    written = 0
    for year in range(start_jalali_year, end_jalali_year + 1):
        await asyncio.sleep(IEE_REQUEST_SPACING_SECONDS)
        try:
            rows = await fetch_monthly_prices(client, base_url, year)
        except httpx.HTTPError as exc:
            logger.warning("historical_ingestion: year %s failed, skipping: %s", year, exc)
            continue

        quotes = parse_monthly_prices(rows)
        async with db_write_lock():
            for quote in quotes:
                await upsert_quote(session, quote)
            await session.commit()
        written += len(quotes)
        logger.info("historical_ingestion: year %s -> %d monthly quotes", year, len(quotes))

    return written


def _parse_jalali_date_utc(value: str) -> datetime | None:
    """Parses IEE's 'YYYY/MM/DD' Jalali date strings (distinct from the
    monthly report's {Year, Months} shape above)."""
    if not isinstance(value, str):
        return None
    parts = value.split("/")
    if len(parts) != 3:
        return None
    try:
        y, m, d = (int(p) for p in parts)
        gregorian = jdatetime.date(y, m, d).togregorian()
        return datetime(gregorian.year, gregorian.month, gregorian.day, tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _jalali_year_window(jalali_year: int, today: jdatetime.date) -> tuple[str, str]:
    """('YYYY/01/01', last day of that year or today, whichever is earlier)."""
    start = jdatetime.date(jalali_year, 1, 1)
    end = min(jdatetime.date(jalali_year + 1, 1, 1) - timedelta(days=1), today)
    return start.strftime("%Y/%m/%d"), end.strftime("%Y/%m/%d")


async def fetch_derivative_free_power_statistics(
    client: httpx.AsyncClient,
    base_url: str,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict]:
    """One date window of the statistics report; defaults to the current
    Jalali year to date. Keep windows to about a year - see module docstring."""
    return await _fetch_statistics(client, base_url, DERIVATIVE_FREE_STATS_PATH, from_date, to_date)


async def _fetch_statistics(
    client: httpx.AsyncClient,
    base_url: str,
    path: str,
    from_date: str | None,
    to_date: str | None,
) -> list[dict]:
    """Shared by IEE's paged per-contract statistics reports (same params/shape)."""
    default_from, default_to = _jalali_year_window(jdatetime.date.today().year, jdatetime.date.today())
    response = await client.get(
        f"{base_url}{path}",
        params={
            "Lang": "fa",
            "start": "0",
            "PageNumber": "1",
            "PageSize": "10000",
            "FromDate": from_date or default_from,
            "ToDate": to_date or default_to,
        },
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ElectricityMarketDashboard/1.0; +data-collector)",
            "Accept": "application/json",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not body.get("isSuccess"):
        return []
    results = body.get("results")
    return results if isinstance(results, list) else []


def parse_derivative_free_power_statistics(rows: list[dict]) -> list[NormalizedQuote]:
    quotes: list[NormalizedQuote] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = row.get("energySymbol")
        observed_at = _parse_jalali_date_utc(row.get("date"))
        if not symbol or observed_at is None:
            continue
        # Days without trades carry a placeholder closingPrice ("1" before a
        # contract's first trade, else the previous close), same as TSETMC's
        # daily list - not observations, and they drew fake 1-Rial prices.
        if not _parse_comma_number(row.get("tradeNo")):
            continue
        try:
            quotes.append(
                NormalizedQuote(
                    source_id=SOURCE_ID,
                    # Not prefixed - same energySymbol TSETMC uses for the
                    # identical contract, see module docstring.
                    source_symbol=symbol,
                    observed_at=observed_at,
                    last_price=_parse_comma_number(row.get("closingPrice")),
                    volume=_parse_comma_number(row.get("tradeVolumeTooltip")),
                    value=_parse_comma_number(row.get("tradeValue")),
                    transaction_count=(
                        int(v) if (v := _parse_comma_number(row.get("tradeNo"))) is not None else None
                    ),
                    raw=row,
                )
            )
        except Exception as exc:  # noqa: BLE001 - one bad row must not drop the batch
            logger.warning("historical_ingestion: skipping unparseable derivative-free-stats row: %s", exc)
            continue
    return quotes


async def backfill_iee_derivative_free_power_history(
    session: AsyncSession,
    client: httpx.AsyncClient,
    base_url: str,
    start_jalali_year: int = DERIVATIVE_FREE_STATS_EARLIEST_JALALI_YEAR,
    end_jalali_year: int | None = None,
) -> int:
    """Backfill the Free Power derivative market's complete per-contract
    daily statistics history, one Jalali year per request. Idempotent -
    re-running re-upserts the same (source, symbol, day) key, safe to
    re-run on every app startup. A failed year is logged and skipped, not
    fatal to the others.
    """
    today = jdatetime.date.today()
    end_jalali_year = end_jalali_year or today.year
    written = 0
    for year in range(start_jalali_year, end_jalali_year + 1):
        from_date, to_date = _jalali_year_window(year, today)
        await asyncio.sleep(IEE_REQUEST_SPACING_SECONDS)
        try:
            rows = await fetch_derivative_free_power_statistics(client, base_url, from_date, to_date)
        except httpx.HTTPError as exc:
            logger.warning("historical_ingestion: derivative free stats %s failed, skipping: %r", year, exc)
            continue

        quotes = parse_derivative_free_power_statistics(rows)
        async with db_write_lock():
            for quote in quotes:
                await upsert_quote(session, quote)
            await session.commit()
        written += len(quotes)
        logger.info("historical_ingestion: derivative free power history %s -> %d quotes", year, len(quotes))

    return written


def aggregate_power_baseload_daily(rows: list[dict]) -> list[NormalizedQuote]:
    """Per-contract report rows -> one base-load VWAP quote per trading day.

    price = total traded value / total kWh across that day's base-load
    contracts (Rials/kWh; for a single contract this equals IEE's own
    avgPrice, e.g. 2,958,134,731,920 / 869,950,080 = 3,400). Days and
    contracts without trades are left out - their prices are placeholders.
    """
    by_day: dict[datetime, list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("contract") or "").startswith(_BASELOAD_PREFIX):
            continue
        trades = _parse_comma_number(row.get("tradeNo"))
        value = _parse_comma_number(row.get("tradeValueNumber")) or _parse_comma_number(row.get("tradeValue"))
        kwh = _parse_comma_number(row.get("kiloWattHours"))
        observed_at = _parse_jalali_date_utc(row.get("date"))
        if not trades or not value or not kwh or observed_at is None:
            continue
        by_day.setdefault(observed_at, []).append(
            {
                "contract": row.get("contract"),
                "energySymbol": row.get("energySymbol"),
                "avgPrice": _parse_comma_number(row.get("avgPrice")),
                "tradeNo": int(trades),
                "kWh": kwh,
                "value": value,
            }
        )

    quotes: list[NormalizedQuote] = []
    for observed_at, contracts in sorted(by_day.items()):
        value = sum(c["value"] for c in contracts)
        kwh = sum(c["kWh"] for c in contracts)
        quotes.append(
            NormalizedQuote(
                source_id=SOURCE_ID,
                source_symbol=POWER_BASELOAD_SYMBOL,
                observed_at=observed_at,
                last_price=round(value / kwh, 2),
                volume=kwh,
                value=value,
                transaction_count=sum(c["tradeNo"] for c in contracts),
                raw={
                    "date": jdatetime.date.fromgregorian(date=observed_at.date()).strftime("%Y/%m/%d"),
                    "unit": "Rials/kWh, volume-weighted over base-load contracts",
                    "contracts": contracts,
                },
            )
        )
    return quotes


async def backfill_power_baseload_history(
    session: AsyncSession,
    client: httpx.AsyncClient,
    base_url: str,
    start_jalali_year: int = POWER_STATS_EARLIEST_JALALI_YEAR,
    end_jalali_year: int | None = None,
) -> int:
    """Fetch the main power market's daily statistics one Jalali year per
    request and store the base-load daily VWAP. Idempotent upserts keyed on
    (source, symbol, day), so re-running for the current year just updates
    today's row. A failed year is logged and skipped."""
    today = jdatetime.date.today()
    end_jalali_year = end_jalali_year or today.year
    written = 0
    for year in range(start_jalali_year, end_jalali_year + 1):
        from_date, to_date = _jalali_year_window(year, today)
        await asyncio.sleep(IEE_REQUEST_SPACING_SECONDS)
        try:
            rows = await _fetch_statistics(client, base_url, POWER_DERIVATIVE_STATS_PATH, from_date, to_date)
        except httpx.HTTPError as exc:
            logger.warning("historical_ingestion: power derivative stats %s failed, skipping: %r", year, exc)
            continue

        quotes = aggregate_power_baseload_daily(rows)
        async with db_write_lock():
            for quote in quotes:
                await upsert_quote(session, quote)
            await session.commit()
        written += len(quotes)
        logger.info("historical_ingestion: power base-load daily %s -> %d days (%d rows)", year, len(quotes), len(rows))

    return written
