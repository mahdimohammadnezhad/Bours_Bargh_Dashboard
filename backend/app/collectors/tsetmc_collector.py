"""TSETMC Energy Exchange (electricity) collector - Free Power ("برق آزاد") market.

VERIFIED against live responses - endpoints and parameters were captured
via real browser network traffic (Playwright + network interception) while
navigating tsetmc.ir's "بورس انرژی ایران" > "برق آزاد" tab, not guessed
and not read from a JS bundle this time. See docs/DATA_SOURCES.md for the
full investigation notes and sample payloads.

Key correction from an earlier version of this collector: `flow=64` (used
before) is TSETMC's general "Power" board, not the Free electricity market
the dashboard is actually meant to track. The real "برق آزاد" tab uses
**flow=60** throughout - confirmed by the fact that flow=60's aggregate
numbers from `GetPowerOverview` match a specific contract's own
`GetClosingPriceInfo` numbers exactly on days when only one contract
traded (both showed qTotCap=2,973,600,000 for 2026-09-05).

Four endpoints, all under {base} = https://cdn.tsetmc.com/api:

    GET /Energy/GetPowerOverview/60
        -> {"powerOverview": {"totalCount", "totalValue", "mazadCount",
             "mazadValue", "f60_MarketActivityQTotCap",
             "f60_MarketActivityZTotTran", "marketStateTitle", ...}}
        "بازار برق آزاد در یک نگاه" (Free Power Market At a Glance).

    GET /BestLimits/GetBestLimitsTopPower/EnergyPowerBuy/60/4/0
    GET /BestLimits/GetBestLimitsTopPower/EnergyPowerSell/60/4/0
        -> {"bestLimitsTop": [{"insCode", "title",
             "powerInstrumentDate": {"loadType": 0, "energySymbol", ...},
             "pMeDem", "qTitMeDem", "zOrdMeDem",   (demand/buy side)
             "pMeOf", "qTitMeOf", "zOrdMeOf",       (offer/sell side)
             "val"}, ...]}
        "برترین قیمت تقاضا - بار پایه" (EnergyPowerBuy) and
        "برترین قیمت عرضه - بار پایه" (EnergyPowerSell). The trailing
        `/0` is `loadType=0`, confirmed to mean "بار پایه" (base load) -
        every row's `powerInstrumentDate.loadType` came back 0. Only the
        Dem fields are populated on Buy rows and only the Of fields on
        Sell rows in practice; the other side's fields come back zeroed
        rather than absent.

    GET /Instrument/GetInstrumentInfo/{insCode}
    GET /ClosingPrice/GetClosingPriceInfo/{insCode}
        Per-contract current snapshot, called once a live insCode is
        known from the two endpoints above - confirms Energy contracts
        have real TSETMC insCodes usable against the *general*
        (non-Energy) instrument/closing-price API family, not just the
        Energy-specific one.

Historical daily OHLC-style data per contract
(`ClosingPrice/GetClosingPriceDailyList/{insCode}/{n}`) is fetched
separately by `backfill_tsetmc_contract_history` in
app/services/historical_ingestion.py, once per newly-seen insCode - not
every cycle, since it returns many days of history at once.
"""

from datetime import datetime, timezone
from typing import Any

import httpx

from app.collectors.base import BaseCollector, NormalizedQuote
from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

# 60 = the "flow" id the production tsetmc.ir frontend uses specifically
# for the Free ("آزاد") power market tab - see module docstring. This is
# distinct from flow=64 (general "Power" board).
FREE_POWER_FLOW_ID = 60
BEST_LIMITS_TOP = 4
BASE_LOAD_TYPE = 0

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ElectricityMarketDashboard/1.0; +data-collector)",
    "Accept": "application/json",
}


class TSETMCCollector(BaseCollector):
    source_id = "tsetmc"
    name = "TSETMC Energy Exchange"
    base_url = settings.TSETMC_BASE_URL
    configured = True

    def __init__(self) -> None:
        super().__init__()
        # insCodes we've already kicked off a one-time history backfill
        # for, so a cycle that keeps seeing the same handful of contracts
        # doesn't refetch their whole daily history every 5-8 seconds.
        self.known_ins_codes: set[str] = set()

    async def fetch_raw(self, client: httpx.AsyncClient) -> Any:
        overview = await self._get(client, f"/Energy/GetPowerOverview/{FREE_POWER_FLOW_ID}")
        demand = await self._get(
            client, f"/BestLimits/GetBestLimitsTopPower/EnergyPowerBuy/{FREE_POWER_FLOW_ID}/{BEST_LIMITS_TOP}/{BASE_LOAD_TYPE}"
        )
        supply = await self._get(
            client, f"/BestLimits/GetBestLimitsTopPower/EnergyPowerSell/{FREE_POWER_FLOW_ID}/{BEST_LIMITS_TOP}/{BASE_LOAD_TYPE}"
        )

        ins_codes = self._extract_ins_codes(demand) | self._extract_ins_codes(supply)
        contracts: dict[str, Any] = {}
        for ins_code in ins_codes:
            try:
                contracts[ins_code] = await self._get(client, f"/ClosingPrice/GetClosingPriceInfo/{ins_code}")
            except httpx.HTTPError as exc:
                logger.warning("tsetmc: GetClosingPriceInfo failed for %s: %s", ins_code, exc)

        # First time we've ever seen a contract: pull its daily history too
        # (not every cycle - that would refetch the same weeks of history
        # every 5-8s). These land in `parse()` as ordinary historical
        # NormalizedQuotes under the same symbol as the live quote, since
        # they're the same instrument's timeline at different points.
        new_ins_codes = ins_codes - self.known_ins_codes
        self.known_ins_codes |= ins_codes
        daily_history: dict[str, Any] = {}
        for ins_code in new_ins_codes:
            try:
                daily_history[ins_code] = await self._get(
                    client, f"/ClosingPrice/GetClosingPriceDailyList/{ins_code}/2000"
                )
            except httpx.HTTPError as exc:
                logger.warning("tsetmc: GetClosingPriceDailyList failed for %s: %s", ins_code, exc)

        return {
            "overview": overview,
            "demand": demand,
            "supply": supply,
            "contracts": contracts,
            "daily_history": daily_history,
        }

    async def _get(self, client: httpx.AsyncClient, path: str) -> Any:
        response = await client.get(f"{self.base_url}{path}", timeout=settings.HTTP_TIMEOUT_SECONDS, headers=_HEADERS)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _extract_ins_codes(best_limits_raw: Any) -> set[str]:
        rows = best_limits_raw.get("bestLimitsTop") if isinstance(best_limits_raw, dict) else None
        if not isinstance(rows, list):
            return set()
        return {row["insCode"] for row in rows if isinstance(row, dict) and row.get("insCode")}

    @staticmethod
    def _extract_symbol_map(best_limits_raw: Any) -> dict[str, str]:
        rows = best_limits_raw.get("bestLimitsTop") if isinstance(best_limits_raw, dict) else None
        if not isinstance(rows, list):
            return {}
        mapping: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict) or not row.get("insCode"):
                continue
            symbol = (row.get("powerInstrumentDate") or {}).get("energySymbol")
            if symbol:
                mapping[row["insCode"]] = symbol
        return mapping

    def parse(self, raw: Any) -> list[NormalizedQuote]:
        if not isinstance(raw, dict):
            return []
        quotes: list[NormalizedQuote] = []

        overview = self._parse_overview(raw.get("overview"))
        if overview is not None:
            quotes.append(overview)

        # energySymbol (e.g. "DDP00PFBEXW050621") is the same identifier
        # IEE's own statistics use for this exact contract (confirmed by
        # cross-checking a live capture from both sites on 2026-09-05) -
        # using it instead of the opaque insCode makes the two sources'
        # data directly comparable per-symbol, which insCode alone would
        # not. Derived here (not precomputed in fetch_raw) so parse() stays
        # a pure function of its input, testable without extra plumbing.
        symbol_map = {**self._extract_symbol_map(raw.get("demand")), **self._extract_symbol_map(raw.get("supply"))}

        quotes.extend(self._parse_best_limits(raw.get("demand"), side="DEMAND"))
        quotes.extend(self._parse_best_limits(raw.get("supply"), side="SUPPLY"))
        quotes.extend(self._parse_contracts(raw.get("contracts"), symbol_map))
        quotes.extend(self._parse_daily_history(raw.get("daily_history"), symbol_map))

        return quotes

    @staticmethod
    def _contract_symbol(ins_code: str, symbol_map: dict[str, str]) -> str:
        # Prefer the human-readable, cross-source energySymbol; fall back
        # to the insCode if a map entry is missing (e.g. daily_history for
        # a contract fetched in an earlier cycle whose symbol_map entry
        # wasn't carried over - still correct, just less readable).
        return symbol_map.get(ins_code) or f"INSCODE_{ins_code}"

    def _parse_overview(self, raw: Any) -> NormalizedQuote | None:
        if not isinstance(raw, dict):
            return None
        overview = raw.get("powerOverview") if isinstance(raw.get("powerOverview"), dict) else raw
        value_field = f"f{FREE_POWER_FLOW_ID}_MarketActivityQTotCap"
        if value_field not in overview:
            return None
        try:
            return NormalizedQuote(
                source_id=self.source_id,
                source_symbol="TSETMC_FREE_POWER_OVERVIEW",
                observed_at=datetime.now(timezone.utc),
                # The flow-specific QTotCap, not `totalValue`: totalValue
                # is some other aggregate - 4.67 trillion vs this market's
                # 2.97 billion on 2026-09-05, and 0 all through an open
                # session with real trades on 2026-10-11 - while QTotCap
                # matches the market's own contract trades (see module
                # docstring) and IEE's Free-market daily total.
                value=self._to_float(overview.get(value_field)),
                transaction_count=self._to_int(overview.get(f"f{FREE_POWER_FLOW_ID}_MarketActivityZTotTran")),
                raw=overview,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("tsetmc: skipping unparseable Free power overview: %s", exc)
            return None

    def _parse_best_limits(self, raw: Any, side: str) -> list[NormalizedQuote]:
        if not isinstance(raw, dict):
            return []
        rows = raw.get("bestLimitsTop")
        if not isinstance(rows, list):
            return []

        price_field, volume_field, count_field = (
            ("pMeDem", "qTitMeDem", "zOrdMeDem") if side == "DEMAND" else ("pMeOf", "qTitMeOf", "zOrdMeOf")
        )
        observed_at = datetime.now(timezone.utc)
        quotes: list[NormalizedQuote] = []
        for level, row in enumerate(rows[:BEST_LIMITS_TOP], start=1):
            if not isinstance(row, dict):
                continue
            try:
                quotes.append(
                    NormalizedQuote(
                        source_id=self.source_id,
                        source_symbol=f"TSETMC_FREE_{side}_L{level}",
                        observed_at=observed_at,
                        last_price=self._to_float(row.get(price_field)),
                        volume=self._to_float(row.get(volume_field)),
                        value=self._to_float(row.get("val")),
                        transaction_count=self._to_int(row.get(count_field)),
                        raw=row,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - one bad row must not drop the batch
                logger.warning("tsetmc: skipping unparseable best-limits row (%s L%d): %s", side, level, exc)
                continue
        return quotes

    def _parse_contracts(self, raw: Any, symbol_map: dict[str, str]) -> list[NormalizedQuote]:
        if not isinstance(raw, dict):
            return []
        observed_at = datetime.now(timezone.utc)
        quotes: list[NormalizedQuote] = []
        for ins_code, payload in raw.items():
            # known_ins_codes is updated authoritatively in fetch_raw (from
            # every insCode seen in demand/supply, whether or not its
            # closing-price fetch succeeded) - not duplicated here.
            info = payload.get("closingPriceInfo") if isinstance(payload, dict) else None
            if not isinstance(info, dict):
                continue
            try:
                last_price = self._real_price(info.get("pClosing"))
                yesterday = self._real_price(info.get("priceYesterday"))
                # Live `priceChange` stays 0.0 during the session (e.g. 67,937
                # vs a 45,000 previous close on 2026-10-11), so the change is
                # computed from the same two fields TSETMC displays.
                change = last_price - yesterday if last_price is not None and yesterday is not None else None
                quotes.append(
                    NormalizedQuote(
                        source_id=self.source_id,
                        source_symbol=self._contract_symbol(ins_code, symbol_map),
                        observed_at=observed_at,
                        last_price=last_price,
                        close_price=self._real_price(info.get("pDrCotVal")),
                        price_change=change,
                        price_change_percent=change / yesterday * 100 if change is not None else None,
                        volume=self._to_float(info.get("qTotTran5J")),
                        value=self._to_float(info.get("qTotCap")),
                        transaction_count=self._to_int(info.get("zTotTran")),
                        raw=info,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("tsetmc: skipping unparseable contract %s: %s", ins_code, exc)
                continue
        return quotes

    def _parse_daily_history(self, raw: Any, symbol_map: dict[str, str]) -> list[NormalizedQuote]:
        if not isinstance(raw, dict):
            return []
        quotes: list[NormalizedQuote] = []
        for ins_code, payload in raw.items():
            days = payload.get("closingPriceDaily") if isinstance(payload, dict) else None
            if not isinstance(days, list):
                continue
            for day in days:
                if not isinstance(day, dict):
                    continue
                observed_at = self._parse_deven(day.get("dEven"))
                if observed_at is None:
                    continue
                # The list has a row for every calendar day, traded or not.
                # On no-trade days pClosing is a placeholder: 1 before the
                # contract ever traded (1,515 of 1,792 rows stored by
                # 2026-10-11), the previous close after. Storing those drew
                # fake crashes to 1 Rial on the price chart, so only actual
                # trading days are kept - matching IEE's own statistics.
                if not self._to_int(day.get("zTotTran")):
                    continue
                try:
                    quotes.append(
                        NormalizedQuote(
                            # Same symbol as the live contract quote in
                            # _parse_contracts - this is that same
                            # instrument's timeline, just older points.
                            source_id=self.source_id,
                            source_symbol=self._contract_symbol(ins_code, symbol_map),
                            observed_at=observed_at,
                            last_price=self._to_float(day.get("pClosing")),
                            close_price=self._to_float(day.get("pDrCotVal")),
                            price_change=self._to_float(day.get("priceChange")),
                            volume=self._to_float(day.get("qTotTran5J")),
                            value=self._to_float(day.get("qTotCap")),
                            transaction_count=self._to_int(day.get("zTotTran")),
                            raw=day,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("tsetmc: skipping unparseable daily history row for %s: %s", ins_code, exc)
                    continue
        return quotes

    @classmethod
    def _real_price(cls, value: Any) -> float | None:
        """TSETMC fills price fields with 1 when there is no price yet (e.g.
        priceYesterday of a contract on its first trading day). No real
        electricity price is <= 1 Rial, so treat those as missing - one such
        placeholder as the reference would show an +8,500,000% change."""
        price = cls._to_float(value)
        return price if price is not None and price > 1 else None

    @staticmethod
    def _parse_deven(value: Any) -> datetime | None:
        """TSETMC's `dEven` is a Gregorian date as an int, e.g. 20260902."""
        if value is None:
            return None
        try:
            text = str(int(value))
            if len(text) != 8:
                return None
            return datetime(int(text[:4]), int(text[4:6]), int(text[6:8]), tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
