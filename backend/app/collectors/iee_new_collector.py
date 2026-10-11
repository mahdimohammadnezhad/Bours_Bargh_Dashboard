"""Iran Energy Exchange (IEE) - new site collector.

VERIFIED against live responses - see docs/DATA_SOURCES.md. The
newsite.iee.ir page itself is a React SPA shell with no data; the real API
host was found by downloading its production JS bundle and grepping for
`https://` string literals, which turned up `https://webapi.iee.ir/api`.
Reading the bundle's API client further (same technique as the TSETMC
collector) surfaced the exact endpoints below, both confirmed live:

    GET {base}/Home/GetTradesSummary_Power
        -> {"results": [{"period": "Day"|"Week"|"Month"|"Year",
                          "market": "Power"|"Green"|"Free",
                          "tradedValue": <float>, "tradedVolume": <float>,
                          "avgPrice": <float>, "tradeNo": <int>}, ...],
            "isSuccess": true, ...}
        Aggregated trade stats per electricity sub-market and period. No
        auth, no params.

    GET {base}/PowerFreeMarket/GetFreePowerMarketAtAGlance?Lang=fa
        -> {"results": [{"marketState": "باز"|"بسته",
                          "totalTradesValue": "3,528,000,000,000" (comma-
                              formatted string, full Rials),
                          "totalTradesVolume": 200000 (numeric),
                          "totalTradesCount": "27" (string),
                          "kiloWattHours": "33,600,000", ...}],
            "isSuccess": true, ...}
        Live snapshot of the Free power market specifically, including the
        Persian market-open/closed state text.

    GET {base}/PowerMarket/GetDerivativePowerMarketAtGlance?Lang=fa
        -> {"results": [{"marketStatus": "بسته"|"باز", "totalTradeNo": "111",
                          "totalTradeValue": "594,241,797,738" (comma str),
                          "totalKiloWattHours": "164,696,076" (comma str),
                          "trades": [{"id": 193954,
                                      "contract": "بارپايه ماهانه 14050501",
                                      "date": "2026/08/22",
                                      "closingPrice": "3,533" (comma str),
                                      "minPrice": "3,450", "maxPrice": "3,600",
                                      "avgPrice": "3533",
                                      "tradeValueNumber": 399919031520 (numeric!),
                                      "tradeNoNumber": 27 (numeric!),
                                      "tradeVolumeNumber": 152126 (numeric!),
                                      "insCode": "46989496890754718",
                                      "kiloWattHours": "113,181,744", ...}, ...]}],
            "isSuccess": true, ...}
        Per-contract trade board for the derivative power market - the
        best per-instrument quotes/trade-board data found across either
        site. Confirmed 448 individual contracts on 2026-08-22. Despite
        `closingPrice`/`minPrice`/`maxPrice`/`avgPrice` being comma-string
        formatted like elsewhere on this site, `tradeValueNumber`,
        `tradeNoNumber`, and `tradeVolumeNumber` are already plain JSON
        numbers - use those directly instead of re-parsing their string
        siblings.

        A note on Persian text here: an earlier investigation pass
        suspected this endpoint had a response-encoding bug because
        `contract`/`marketStatus` printed as mojibake to a terminal. That
        was a false alarm - the raw HTTP bytes are correct UTF-8 (content
        header says `charset=utf-8`, and decoding `contract` by hand
        reproduces readable Persian, e.g. "بارپايه ماهانه 14050501"). The
        garbling was the Windows console's own code page mangling Persian
        `print()` output during manual debugging, not a defect in the data
        or in httpx's decoding - `response.json()` (used in `fetch_raw`
        below) was never affected. Nothing needed fixing in the data path
        itself; it just needed re-checking outside a terminal print.

Unit note (inferred, not confirmed by IEE documentation - there isn't
any): GetTradesSummary_Power's `tradedValue` appears to be in *millions of
Rials*, not Rials. Evidence: on 2026-08-22 this endpoint reported
Day/Power tradedValue=595715.997738 while TSETMC's independently-run
GetPowerOverview/64 (see tsetmc_collector.py) reported the same day's
Power-market total as 594,241,797,738 Rials for the same market - a ratio
of ~1,000,000. GetFreePowerMarketAtAGlance's and
GetDerivativePowerMarketAtGlance's value fields, by contrast, are already
in full Rials - the latter's `totalTradeValue` ("594,241,797,738") matches
TSETMC's number for the same day almost exactly, which is itself a useful
cross-source consistency check (see docs/DATA_SOURCES.md). Re-confirmed
exactly on 2026-10-11: Day/Free tradedValue=4,160,539.2204 vs TSETMC's
f60 total of 4,160,539,220,400 Rials - so `value` is now normalized to
Rials (x1,000,000) like every other source; before that the dashboard
showed these totals a million times too small. `raw` keeps the untouched
original value.
"""

import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.collectors.base import BaseCollector, NormalizedQuote
from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

_TRADES_SUMMARY_PATH = "/Home/GetTradesSummary_Power"
_FREE_GLANCE_PATH = "/PowerFreeMarket/GetFreePowerMarketAtAGlance"
_DERIVATIVE_GLANCE_PATH = "/PowerMarket/GetDerivativePowerMarketAtGlance"
_MILLION = 1_000_000


class IEENewCollector(BaseCollector):
    source_id = "iee_new"
    name = "Iran Energy Exchange (new site)"
    base_url = settings.IEE_NEW_BASE_URL
    configured = True
    min_poll_interval = settings.IEE_MIN_POLL_INTERVAL

    async def fetch_raw(self, client: httpx.AsyncClient) -> Any:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ElectricityMarketDashboard/1.0; +data-collector)",
            "Accept": "application/json",
        }
        summary_resp = await client.get(
            f"{self.base_url}{_TRADES_SUMMARY_PATH}",
            timeout=settings.HTTP_TIMEOUT_SECONDS,
            headers=headers,
        )
        summary_resp.raise_for_status()

        glance_resp = await client.get(
            f"{self.base_url}{_FREE_GLANCE_PATH}",
            params={"Lang": "fa"},
            timeout=settings.HTTP_TIMEOUT_SECONDS,
            headers=headers,
        )
        glance_resp.raise_for_status()

        derivative_resp = await client.get(
            f"{self.base_url}{_DERIVATIVE_GLANCE_PATH}",
            params={"Lang": "fa"},
            timeout=settings.HTTP_TIMEOUT_SECONDS,
            headers=headers,
        )
        derivative_resp.raise_for_status()

        return {
            "trades_summary": summary_resp.json(),
            "free_glance": glance_resp.json(),
            "derivative_glance": derivative_resp.json(),
        }

    def parse(self, raw: Any) -> list[NormalizedQuote]:
        if not isinstance(raw, dict):
            return []

        quotes: list[NormalizedQuote] = []
        quotes.extend(self._parse_trades_summary(raw.get("trades_summary")))
        quotes.extend(self._parse_free_glance(raw.get("free_glance")))
        quotes.extend(self._parse_derivative_glance(raw.get("derivative_glance")))
        return quotes

    def _parse_trades_summary(self, payload: Any) -> list[NormalizedQuote]:
        if not isinstance(payload, dict):
            return []
        results = payload.get("results")
        if not isinstance(results, list):
            return []

        quotes: list[NormalizedQuote] = []
        for row in results:
            try:
                if not isinstance(row, dict) or row.get("period") != "Day":
                    continue
                market = row.get("market")
                if not market:
                    continue
                traded_value_millions = self._to_float(row.get("tradedValue"))
                quotes.append(
                    NormalizedQuote(
                        source_id=self.source_id,
                        source_symbol=f"IEE_{str(market).upper()}_DAY",
                        observed_at=datetime.now(timezone.utc),
                        last_price=self._to_float(row.get("avgPrice")),
                        volume=self._to_float(row.get("tradedVolume")),
                        # Millions of Rials at the source (see module
                        # docstring) - normalized to Rials like every other
                        # `value`, otherwise 4.16 trillion displays as "4.2M".
                        value=traded_value_millions * _MILLION if traded_value_millions is not None else None,
                        transaction_count=self._to_int(row.get("tradeNo")),
                        raw=row,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - one bad row must not drop the batch
                logger.warning("iee_new: skipping unparseable trades-summary row: %s", exc)
                continue
        return quotes

    def _parse_free_glance(self, payload: Any) -> list[NormalizedQuote]:
        if not isinstance(payload, dict):
            return []
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            return []

        row = results[0]
        if not isinstance(row, dict):
            return []
        try:
            return [
                NormalizedQuote(
                    source_id=self.source_id,
                    source_symbol="IEE_FREE_LIVE",
                    observed_at=datetime.now(timezone.utc),
                    volume=self._to_float(row.get("totalTradesVolume")),
                    value=self._parse_comma_number(row.get("totalTradesValue")),
                    transaction_count=self._to_int(self._parse_comma_number(row.get("totalTradesCount"))),
                    raw=row,
                )
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("iee_new: skipping unparseable free-market-glance row: %s", exc)
            return []

    def _parse_derivative_glance(self, payload: Any) -> list[NormalizedQuote]:
        if not isinstance(payload, dict):
            return []
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            return []

        overview = results[0]
        if not isinstance(overview, dict):
            return []

        quotes: list[NormalizedQuote] = []
        observed_at = datetime.now(timezone.utc)

        try:
            quotes.append(
                NormalizedQuote(
                    source_id=self.source_id,
                    source_symbol="IEE_POWER_DERIVATIVE_TOTAL",
                    observed_at=observed_at,
                    value=self._parse_comma_number(overview.get("totalTradeValue")),
                    transaction_count=self._to_int(self._parse_comma_number(overview.get("totalTradeNo"))),
                    raw={k: v for k, v in overview.items() if k != "trades"},
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("iee_new: skipping unparseable derivative-glance overview: %s", exc)

        for trade in overview.get("trades") or []:
            try:
                if not isinstance(trade, dict):
                    continue
                ins_code = trade.get("insCode")
                if not ins_code:
                    continue
                quotes.append(
                    NormalizedQuote(
                        source_id=self.source_id,
                        source_symbol=f"IEE_POWER_CONTRACT_{ins_code}",
                        observed_at=observed_at,
                        last_price=self._parse_comma_number(trade.get("closingPrice")),
                        volume=self._to_float(trade.get("tradeVolumeNumber")),
                        value=self._to_float(trade.get("tradeValueNumber")),
                        transaction_count=self._to_int(trade.get("tradeNoNumber")),
                        raw=trade,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - one bad contract row must not drop the batch
                logger.warning("iee_new: skipping unparseable derivative contract row: %s", exc)
                continue

        return quotes

    @staticmethod
    def _parse_comma_number(value: Any) -> float | None:
        """IEE formats several numeric fields as comma-grouped strings, e.g. '3,528,000,000,000'."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = re.sub(r"[,\s]", "", value)
            try:
                return float(cleaned)
            except ValueError:
                return None
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
