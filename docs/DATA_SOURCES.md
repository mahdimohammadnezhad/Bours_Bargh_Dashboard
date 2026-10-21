# Data Sources — Investigation Report

Status legend:
- `VERIFIED` — a real HTTP request was made from this project and a response was captured and inspected. This is the only status a collector may be built against.
- `VERIFIED (found in source, untested)` — the exact endpoint/params were read out of a site's own production JS bundle (so it's not a guess), but a live call has not yet been made to confirm the response shape.
- `UNVERIFIED` — a URL pattern or shape believed plausible but not confirmed by any means. Must not be trusted in production.
- `UNKNOWN` — no information found at all.

**How these were actually found (2026-08-22):** direct HTTP access to `tsetmc.*` and `iee.ir` domains was unreliable from this development environment for most of this project (see "Connectivity history" below) until the user added the three sites to a VPN allow-list. Once reachable, the sites were **not** scraped by guessing endpoint names. Instead, each site's own production frontend was downloaded and read:

1. Fetch the page HTML, find the `<script src="...">` bundle path (all three relevant frontends — `tsetmc.ir`, `newsite.iee.ir` — are React SPAs; the bundle hash changes on every deploy, so it must be re-resolved from the current page, never hardcoded).
2. Download that JS bundle (several MB, minified but not obfuscated).
3. Grep it for `/api/` path literals and for the axios/fetch call sites that build request URLs, e.g. `getPowerOverview: e => get(base + "/Energy/GetPowerOverview/" + e)`.
4. Read the *calling* code (React components) to see what real argument values are passed in production (e.g. `getPowerOverview(64)`), instead of guessing parameters.
5. Call the resulting URL for real and capture the JSON.

This is why the endpoints below come with exact paths, exact parameter values seen in production, and real sample payloads, rather than best-guess field names.

### Connectivity history (why some of this took multiple sessions)

- Early in this project, this environment had no route to `tsetmc.*`/`iee.ir` at all (connection timeouts).
- A later session sometimes reached `cdn.tsetmc.com` (got a real `404`) but not consistently, and `newsite.iee.ir`/`oldsite.iee.ir` returned `200` with just the SPA HTML shell — confirming the sites were real and live, but not enough to extract API endpoints before connectivity dropped again.
- The user clarified they were connected through a VPN that routes non-Iranian traffic away from Iran-domestic sites, which explained the intermittent pattern.
- The user then added `tsetmc.ir`, `newsite.iee.ir`/`webapi.iee.ir`, and `oldsite.iee.ir` to that VPN's allow-list (bypass list), after which all three became reliably reachable and the investigation below was completed for TSETMC and IEE-new. **IEE-old was confirmed reachable (`200 OK`) but its response body has not been inspected yet** — see its section below.
- From 2026-09-05 until 2026-10-11 the collectors stored nothing: every request failed with `All connection attempts failed` (network route), and the circuit breaker kept them parked.

### Re-verification, 2026-10-11 (market open)

Both sources reachable directly from the development machine. Live captures during an open session changed or settled the following:

- **TSETMC `GetPowerOverview/60`: `totalValue` is not this market's traded value.** It read `0.0` throughout an open session with real trades, while `f60_MarketActivityQTotCap` read `265,090,356,000` (7 trades) and matched IEE's Free-market daily total. (In the 2026-09-05 capture `totalValue` was 4.67 trillion against the market's 2.97 billion.) The collector now takes the overview's `value` from `f60_MarketActivityQTotCap`. `marketStateTitle` confirmed as `"باز"` when open.
- **TSETMC `GetBestLimitsTopPower/.../60/4/0`** returns populated bid/ask rows while the market is open (earlier captures were all closed-market and empty).
- **IEE `GetDerivativePowerMarketAtGlance`** lists every listed contract (436 today), but only a handful trade on a given day (7 at capture time). The rest repeat unchanged every poll, so `record_cycle` stores and broadcasts a symbol only when its values change. Storing every listed contract on every cycle had grown the table by ~300k duplicate rows per hour of polling.
- **IEE API is behind a WAF** (`cookiesession1` cookie). Bursts get intermittent `403 Forbidden`, about 1 in 8 cycles at a 5 s interval. IEE now has its own minimum poll interval (`IEE_MIN_POLL_INTERVAL`, default 15 s).
- **`GetDerivativeFreePowerMarketStatistics` no longer answers a whole-history request**: `FromDate=1390/01/01` took ~32 s and returned HTTP 400 `isFailed` ("unknown error"). One-Jalali-year windows return in 4–7 s (1403: 0 rows, 1404: 33, 1405 to date: 200), so the backfill now requests one year at a time.
- `newsite.iee.ir` answers API paths with `406 Not Acceptable`. The API host remains `webapi.iee.ir/api`.
- **`GetTradesSummary_Power.tradedValue` is millions of Rials, now confirmed exactly**: Day/Free `4,160,539.2204` vs TSETMC's `f60_MarketActivityQTotCap` of `4,160,539,220,400` for the same market and day. The collector now stores `value` in Rials (×1,000,000), and stored rows were converted. `raw` keeps the original.
- **Both sources use placeholder prices for "no trade"**: `1` before a contract's first trade, and the previous close on later quiet days. This shows up in TSETMC's `GetClosingPriceDailyList` and `priceYesterday`/`pClosing`, and in IEE's statistics report (`closingPrice: "1"`, `tradeNo: "0"`). IEE's monthly report uses `"0"` for months with no published average. None of these are observations: daily rows without trades and zero monthly prices are skipped, and prices ≤ 1 are treated as missing.
- TSETMC's live `priceChange` stays `0.0` during the session, so a contract's change is computed as `pClosing − priceYesterday`, only when `priceYesterday` is a real price.

---

## Source 1 — TSETMC / Energy Exchange (Electricity)

- Frontend: `https://tsetmc.ir/` — confirmed to be the official Tehran Stock Exchange Technology Management Co. app (page title "`.:TSETMC:. :: مدیریت فناوری بورس تهران`", bundles TradingView's `charting_library.min.js`). `tsetmc.ir` and `tsetmc.com`/`cdn.tsetmc.com` are the same product family — the `tsetmc.ir` frontend calls the `cdn.tsetmc.com` API directly (found as a literal string in its JS bundle: `a=(e,t)=>"https://cdn.tsetmc.com"`, used as the base URL for every API group).
- API base: `https://cdn.tsetmc.com/api` — **use HTTPS**; the collector previously defaulted to `http://` which redirects to `https://` anyway.

### Status: `VERIFIED`

#### `GET /Energy/GetPowerOverview/{flow}`

Found in the bundle as `getPowerOverview: e => get(base + "/Energy/GetPowerOverview/" + e)`, called in production with `e = 64` (`Ra.sP.getPowerOverview(64)`), polled every 120s by the frontend by default (`refreshIntervalSeconds ?? 120`). `64` is not documented anywhere as meaning "electricity" — it is simply the value the live frontend uses to render its own Energy/Power widget, so it is treated as the correct one.

Verified live response (2026-08-22, market closed):

```json
{"powerOverview": {
  "totalCount": 1, "totalValue": 1474200000.00,
  "mazadCount": 0, "mazadValue": 0.00,
  "dpePlus64_MarketActivityQTotCap": 595715997738.00,
  "f64_MarketActivityQTotCap": 594241797738.00,
  "f69_MarketActivityQTotCap": 0.0, "dgePlus69_MarketActivityQTotCap": 0.0,
  "f60_MarketActivityQTotCap": 0.0, "dggPlus60_MarketActivityQTotCap": 0.0,
  "f69_MarketActivityZTotTran": 0.0, "f60_MarketActivityZTotTran": 0.0,
  "f64_MarketActivityZTotTran": 111.00,
  "marketStateTitle": "بسته"
}}
```

Field notes (inferred from names + values, not documented by TSETMC):
- `marketStateTitle` — Persian market-state text. Seen values: `"بسته"` (closed). `"باز"` (open) is expected by analogy with IEE's `marketState` field but has not been observed from this endpoint yet.
- `totalValue` — headline traded value for the day (Rials).
- `f64_MarketActivityQTotCap` / `f64_MarketActivityZTotTran` — traded value / transaction count specifically for flow 64 ("Power"). `f69`/`f60` are presumably two other Energy sub-markets (naming pattern suggests other flow IDs in the same family — not investigated).
- `mazadCount`/`mazadValue` — auction ("مزاد") count/value, separate from continuous trading.
- No price, bid/ask, or per-instrument field exists in this endpoint — it is a **market-wide aggregate**, not a quote list.

This is implemented in `backend/app/collectors/tsetmc_collector.py`, normalized into a single synthetic `NormalizedQuote` (`source_symbol="ENERGY_POWER_FLOW64"`).

#### Other endpoints found in the same bundle (found in source, not yet called)

These came from the same grep pass and are believed real (same bundle, same calling convention as `GetPowerOverview`) but have not been called live. Do not build against these without a live capture first.

| Endpoint | Params seen in source | Purpose (inferred) |
|---|---|---|
| `/api/Energy/GetAuctionOverview/{id}` | called with `0` | Auction ("مزاد") summary. Live-tested once: `{"auctionOverview":{"totalCount":7,"totalValue":134240130000.00,"mazadCount":1,"mazadValue":40716630000.00}}` — **this one IS verified**, param `0` confirmed working. |
| `/api/Energy/GetAuctionById/{id}` | — | Detail for one auction. |
| `/api/Energy/GetAuctionOrderById/{id}/{?}` | — | Order-level detail for an auction. |
| `/api/Energy/GetAuctionTradeById/{id}` | — | Executed-trade detail for an auction. |
| `/api/Energy/GetGetAuctionListItemByType/{type}/{top}/{?}` | called as `getAuctionTop(type, top, flow)` | Auction listing filtered by type (double "Get" is in the vendor's own code, not a typo introduced here). |
| `/api/Instrument/GetInstrumentEnergyFutureByInsCode/{insCode}` | called with `e.insCode` | Per-instrument metadata for an Energy-market instrument — confirms Energy-market instruments have TSETMC `insCode`s usable with the *general* (non-Energy) instrument/trade/closing-price APIs below. |
| `/api/BestLimits/GetBestLimitsTopPower/{type}/{top}/{flow}/{loadType}` | called with `("EnergyPowerSell"\|"EnergyPowerBuy", 4, 6, 3)` | Order-book best bid/ask for the power market. **Live-tested**: both calls returned `200` with `{"bestLimitsTop":[]}` (empty because the market was closed at test time — needs re-testing while the market is open). Note the `flow` value used here was `6`, not `64` — these two "flow" numbers are apparently from different numbering namespaces; do not assume they're interchangeable. |
| `/api/MarketData/GetInstrumentStateTop/{top}` | called with `1` | General top-instruments-by-activity list, **not Energy-specific** — live-tested, returned an unrelated mutual-fund instrument. Not useful for this project as-is. |

General (non-Energy-specific) API groups also seen in the same bundle, listed for completeness since Energy-market instruments apparently have real `insCode`s that work against them: `/api/ClosingPrice/*`, `/api/Trade/*`, `/api/Instrument/*`, `/api/MarketData/*`. None of these were called with an electricity `insCode` yet — the auction/trade endpoints above would need to be called first to obtain one.

### What must still be confirmed
- A response from `GetPowerOverview/64` while the market is **open** (`marketStateTitle` should read `"باز"`), to see whether price/volume-shaped fields appear that aren't present in the closed-market sample above.
- `GetBestLimitsTopPower` with a non-empty order book (market must be open).
- The exact meaning of `flow=64` vs `flow=6`, and what `f69`/`f60` represent.
- Historical/date-parameterized variants (none seen yet in the bundle for the Energy group).

---

## Source 2 — Iranian Energy Exchange (IEE), new site

- Frontend: `https://newsite.iee.ir/Market/PowerMarket/Statistics` — confirmed React SPA (Create React App), page has no server-rendered data.
- **Real API host, found in the bundle: `https://webapi.iee.ir/api`** — this is a different domain than the frontend itself; requests must go to `webapi.iee.ir`, not `newsite.iee.ir`.

### Status: `VERIFIED`

#### `GET /Home/GetTradesSummary_Power`

No parameters, no auth. Verified live response (2026-08-22, trimmed):

```json
{"results": [
  {"period":"Day","market":"Power","tradedValue":595715.997738,"tradedVolume":165023676.00,"avgPrice":4500.00,"tradeNo":112},
  {"period":"Day","market":"Green","tradedValue":283174.35384,"tradedVolume":4204536.00,"avgPrice":67350.00,"tradeNo":22},
  {"period":"Day","market":"Free","tradedValue":3528000.00,"tradedVolume":33600000.00,"avgPrice":105000.00,"tradeNo":27},
  {"period":"Week", "...": "same shape, aggregated over the week"},
  {"period":"Month", "...": "same shape, aggregated over the month"},
  {"period":"Year", "...": "same shape, aggregated over the year"}
], "isSuccess": true, "isFailed": false, "errors": [], "successes": ["عملیات موفق"]}
```

Gives Day/Week/Month/Year × Power/Green/Free = up to 12 rows in one call — directly matches the brief's "daily/weekly/monthly/yearly statistics" requirement (§1/§12) without needing separate historical calls. `market` values seen: `"Power"`, `"Green"`, `"Free"` — three distinct electricity sub-markets on this exchange.

**Unit note (inferred, not documented):** `tradedValue` here appears to be in **millions of Rials**, not Rials. Evidence: this endpoint's `Day`/`Power` row (`tradedValue=595715.997738`) and TSETMC's independently-run `GetPowerOverview/64` (`f64_MarketActivityQTotCap=594241797738`, i.e. ~594.2 billion Rials) describe the same market on the same day; the ratio is ~1,000,000. This is strong circumstantial cross-source evidence but not a documented fact — flagged as inferred in `iee_new_collector.py` and worth re-checking against a second day's data.

Implemented in `backend/app/collectors/iee_new_collector.py`, producing one `NormalizedQuote` per `Day` row (`IEE_POWER_DAY`, `IEE_GREEN_DAY`, `IEE_FREE_DAY`).

#### `GET /PowerFreeMarket/GetFreePowerMarketAtAGlance?Lang=fa`

Verified live response (2026-08-22, market open):

```json
{"results": [{
  "marketState": "باز",
  "totalTradesValue": "3,528,000,000,000", "totalTradesValueTooltip": "3,528,000,012,288",
  "totalTradesValueDollars": "2,868,948",
  "totalTradesCount": "27", "addedTradesCount": "0",
  "totalTradesVolume": 200000, "totalTradeVolumeTooltip": "200,000",
  "kiloWattHours": "33,600,000", "kiloWattHoursTooltip": "33,600,000",
  "currencyRate": 1
}], "isSuccess": true, ...}
```

`marketState`: `"باز"` = open, `"بسته"` (by analogy, not yet observed from this endpoint) = closed. Several numeric fields are **comma-formatted strings** (`totalTradesValue`, `totalTradesCount`, `kiloWattHours`) rather than JSON numbers — `totalTradesVolume` is the one exception, already numeric. `iee_new_collector.py` has a dedicated `_parse_comma_number` helper for this. Unlike `GetTradesSummary_Power` above, `totalTradesValue` here is in **full Rials**, not millions — the two endpoints use different unit conventions for a field with a similar name, which is exactly the kind of per-source inconsistency §40 of the brief warns about.

Implemented as one `NormalizedQuote` (`IEE_FREE_LIVE`) per cycle.

#### `GET /PowerMarket/GetDerivativePowerMarketAtGlance?Lang=fa`

Verified live (2026-08-22, market closed), 448 individual contracts in one response:

```json
{"results": [{
  "marketStatus": "بسته", "totalTradeNo": "111", "totalTradeValue": "594,241,797,738",
  "totalKiloWattHours": "164,696,076",
  "trades": [{
    "id": 193954, "contract": "بارپايه ماهانه 14050501", "date": "2026/08/22",
    "closingPrice": "3,533", "minPrice": "3,450", "maxPrice": "3,600", "avgPrice": "3533",
    "tradeValueNumber": 399919031520, "tradeNoNumber": 27, "tradeVolumeNumber": 152126,
    "insCode": "46989496890754718", "kiloWattHours": "113,181,744"
  }, "... 447 more contracts"]
}], "isSuccess": true, ...}
```

This is the best per-instrument "quotes/trade board" data found across either site — real contract names, prices, and volumes, one row per electricity delivery contract. Its totals (`totalTradeNo: "111"`, `totalTradeValue: "594,241,797,738"`) match TSETMC's `f64_MarketActivityZTotTran`/`QTotCap` for the same day almost exactly, again confirming both platforms describe the same underlying electricity trades.

**Encoding false alarm, resolved:** an earlier pass suspected a response-encoding bug because `contract`/`marketStatus` printed as mojibake (`"�с��� ������ 14050501"`) during manual debugging. Re-investigated properly (raw bytes inspected directly, decoded outside a terminal): the HTTP response is correct UTF-8 (`Content-Type: application/json; charset=utf-8`), and `response.json()` parses it correctly — `contract` decodes to readable Persian, e.g. `"بارپايه ماهانه 14050501"`. The garbling was **the Windows console mangling Persian text during `print()`**, not a defect in the API or in httpx. Nothing in the data pipeline needed fixing; `iee_new_collector.py` has a regression test (`test_derivative_glance_persian_text_round_trips_correctly`) asserting the parsed text is correct, specifically so this doesn't get "fixed" again based on how debug output looks in a terminal.

Implemented in `backend/app/collectors/iee_new_collector.py`: one `NormalizedQuote` per contract (`IEE_POWER_CONTRACT_{insCode}`, using the pre-parsed `tradeValueNumber`/`tradeNoNumber`/`tradeVolumeNumber` fields rather than re-parsing their comma-string siblings), plus one aggregate `IEE_POWER_DERIVATIVE_TOTAL` record.

#### Other endpoints found in the same bundle (found in source, not yet called)

| Endpoint | Likely purpose |
|---|---|
| `/PowerMarket/GetDerivativeFreePowerMarketAtGlance?Lang=fa` | Same shape as `GetFreePowerMarketAtAGlance`, likely for the derivative/futures side of the Free market. |
| `/PowerMarket/GetDerivativeGreenPowerMarketAtGlance?Lang=fa` | Same pattern, for the Green market. |
| `/Home/GetTodayMarketsValues` | Cross-market (not electricity-specific) breakdown of today's exchange activity by market type. Live-tested once: shows "بازار برق" (electricity market) at 97% of that day's total exchange value — useful context for a "market share" style stat, not wired into a collector yet. |

#### `POST /Report/GetPowerMarketMonthlyPrice` — historical monthly price report

**Now VERIFIED and implemented** (`backend/app/services/historical_ingestion.py`). Found by reading the request-building code (not guessed): `{Year: v, Months: [w]}` where v/w come from `moment-jalaali` state - confirming this report is indexed by the **Iranian/Jalali calendar**, not Gregorian. Verified live on 2026-08-30:

```json
POST body: {"Year": 1405, "Months": [1,2,...,12]}
-> {"results": [{"year": 1405, "month": 5,
                  "firstSignboardBaseLoadMidPrice": "3459",
                  "greenSignboardBaseLoadMidPrice": "134811",
                  "freeSignboardBaseLoadMidPrice": "118933", ...}],
    "isSuccess": true, ...}
```

The current in-progress Jalali month returned an empty result while the prior completed month had real data - confirming the report only ever contains completed months (no special "skip current month" handling was needed). Only the `BaseLoad...MidPrice` field per segment (Power/Green/Free) was populated in the captures seen; Low/Mid/High-load and Max-price variants were blank. Ingested via `jdatetime` for the Jalali→Gregorian conversion, backfilling 1402 through the current year (~123 monthly quotes across 4 years) automatically on first startup - see `backend/app/main.py::maybe_run_historical_backfill` and `backend/scripts/backfill_historical.py` for a manual re-run.

#### `GET /PowerMarket/GetDeriativePowerMarketStatistics` — main power market, per-contract daily history

**VERIFIED 2026-10-11 and implemented** (`historical_ingestion.backfill_power_baseload_history`). This is the history behind the temperature/season forecast. The path's "Deriative" spelling is IEE's own: it was read from the Statistics page's call site in the production bundle, not guessed. Same params and row shape as the Free-market statistics endpoint (`Lang, start, PageNumber, PageSize, FromDate, ToDate` with Jalali dates). Rows carry `contract` (e.g. `"بارپايه ماهانه 14050801"`), `date`, `avgPrice`, `tradeNo`, `tradeValueNumber`, `kiloWattHours` and `energySymbol` (always populated, `DAP00PFB…` for base load).

- History: 1398 (148 rows) through today. 5,170 rows by 1405/07; one Jalali year per request in 2–7 s.
- Stored as one daily row, `IEE_POWER_BASELOAD_DAILY`: the volume-weighted average of all traded base-load contracts that day, Σ value / Σ kWh in Rials/kWh. For a single contract this equals IEE's `avgPrice`. The contributing contracts are kept in `raw`. That gives 1,037 trading days (Sat–Wed only).
- What it shows: every year the price rises from Farvardin, peaks in Tir/Mordad (+19–22% above the year's average), and falls to −8…−14% in winter. On top of that there is strong inflation and a jump at Nowruz when the year's price caps reset. 1405 roughly doubled the level (~1,700 → ~3,400).

#### Free Power daily series (default market for forecast / patterns / recommendations)

Verified 2026-10-21. Implemented as `DAILY_SERIES` in `historical_ingestion.py`; select with `?market=` on `/api/analytics/*`.

- **`free_forward`** (default): `GET /PowerMarket/GetDerivativeFreePowerMarketStatistics`. Free Power forward ("سلف") base-load weekly/monthly contracts, which are what tsetmc.ir's Free Power tab quotes as best bids/asks. 260 traded rows on 188 days since 1404/01.
- **`free_physical`**: `GET /PowerFreeMarket/GetPhysicalFreePowerTradesStatistics`. Physical Free Power auctions since 1403: 2,740 rows, 1,954 traded on 232 days. **This report also contains "برق خودتامین" (self-supply, ~11-18k) and plain "برق" auctions** (168 traded rows). Only rows with `instrumentDisplayName == "برق آزاد"` are kept, which leaves 202 days.
- Price = Σ value / Σ `kiloWattHours` (equals each row's own average price). Free Power prices run ~60,000-150,000 Rials/kWh vs ~3,400-4,900 in the main regulated market, so the two must never be mixed.
- **Only ~1.5 years of history and very volatile** (day-to-day log-price sd 0.29-0.43). Walk-forward on 2026-10-21: no model beat "no change" over 14 days (forward base load: 28.7% MAPE), so that is the default. A monthly outlook needs 3+ years and reports `insufficient_data`. Recommendations need at least two independent directional pieces of evidence; otherwise the signal is "mixed".

tsetmc.ir's "بازار برق آزاد در یک نگاه" panel maps as follows: `totalValue`/`totalCount` = physical market; `f60_MarketActivityQTotCap`/`f60_MarketActivityZTotTran` = forward ("سلف") trades; `dggPlus60_MarketActivityQTotCap` = total. Checked against the site on 2026-10-11 (all forward, 265B / 7 trades) and 2026-10-21 (all physical, 95.982B / 3 trades).

## Weather — Open-Meteo (for the price forecast)

- Archive: `https://archive-api.open-meteo.com/v1/archive` (ERA5 reanalysis, ~5-day lag). Forecast: `https://api.open-meteo.com/v1/forecast` (16 days ahead; `past_days` covers the archive lag).
- **VERIFIED 2026-10-11**: daily `temperature_2m_mean/max/min`, `timezone=Asia/Tehran`, multi-location requests (comma-separated `latitude`/`longitude`, one response object per location). No key; free for non-commercial use.
- Implemented in `app/services/weather.py`. The national temperature is a population-weighted mean of 10 large cities. The weights are approximate 2016 census populations: a modelling proxy, not an official statistic. Stored in `weather_daily`; forecast rows are replaced by archive values once observed.
- Relationship found (`/api/analytics/patterns`): on days with a 7-day mean below 20 °C the price sits ~8% below the year's average; at 25–30 °C it is +12%, above 30 °C +15%. Correlation 0.54 over 787 days.

### What must still be confirmed
- Whether these endpoints require rate-limit-friendly headers/cookies under sustained polling (only tested with a handful of one-off requests plus one full `run_cycle()` so far).
- Whether the Green/Free derivative variants add genuinely new contracts or overlap with the Power one.

---

## Source 3 — Iranian Energy Exchange (IEE), old site

- URL: `https://oldsite.iee.ir/PowerMarket/Statistics/Power`

### Status: `VERIFIED` — confirmed to be a stale mirror of Source 2, not a distinct source

The original assumption (legacy ASP.NET WebForms, HTML-table statistics) was **wrong** and has been retracted. What was actually found:

- The page HTML is byte-for-byte the same React SPA shell as `newsite.iee.ir` — same `<title>`, same `schema.org`/`google-site-verification` metadata, same `<div id="root">` structure. Only the JS/CSS bundle filenames differ (`main.73cd4015.js` here vs `main.f20d21ca.js` on the new site).
- `Server: Microsoft-IIS/10.0`, `X-Powered-By: ASP.NET` on both — so "ASP.NET" here just means IIS is serving static files for a React build, not classic WebForms.
- The one real difference: `Last-Modified: Mon, 29 Jun 2026` on oldsite vs same-day-fresh on newsite (checked 2026-08-22) — this is an **older, stale build of the identical app**, not a separate system.
- Downloading and grepping oldsite's own JS bundle confirms it calls the exact same API host as the new site: `https://webapi.iee.ir/api`.

**Conclusion: there is no separate dataset here to build a collector against.** `oldsite.iee.ir` is a leftover deployment hitting the same live backend `IEENewCollector` already polls. Implementing a second collector for it would add duplicate load on the same API for no new data, plus a fragile dependency on a stale build that could disappear or start erroring with no warning. `IEEOldCollector` stays an intentional stub (`configured = False`) — this is a closed investigation, not a pending one.

---

## Data Normalization Requirements

Confirmed, not just anticipated, now that real data exists from two sources:

- **Units genuinely differ per endpoint, even within the same site.** IEE's `GetTradesSummary_Power.tradedValue` is (inferred) millions of Rials; IEE's `GetFreePowerMarketAtAGlance.totalTradesValue` on the very same site is full Rials. TSETMC's `totalValue`/`*_QTotCap` are full Rials. A canonical "value in Rials" field must apply a per-endpoint conversion, not a per-source one.
- **Some sources return numbers as comma-formatted strings** (IEE's `GetFreePowerMarketAtAGlance`), others as native JSON numbers (everything else seen so far) — normalization must not assume either.
- **The same underlying market is genuinely observable from two independent platforms** (TSETMC's flow-64 aggregate and IEE's derivative-power trades board matched to within rounding on 2026-08-22) — this makes the Source Comparison page (§39 of the brief) meaningfully useful, not just a defensive feature, and gives a concrete way to sanity-check either source against the other going forward.
- Every source has a different notion of "instrument": TSETMC's Energy group has real `insCode`s (confirmed via `GetInstrumentEnergyFutureByInsCode`); IEE's derivative power trades also carry an `insCode`-named field with similar-looking numeric IDs, but it has not been confirmed whether these are the *same* ID space as TSETMC's — treat them as source-scoped until proven otherwise.
- Timestamps: neither TSETMC's `GetPowerOverview` nor IEE's `GetTradesSummary_Power`/`GetFreePowerMarketAtAGlance` include a per-response timestamp field — both are point-in-time snapshots with no server-side "as of" marker. The collectors stamp `observed_at` with the collection time (UTC) rather than inventing a source timestamp that doesn't exist.

## Next investigation steps (in priority order)

1. Capture `GetPowerOverview/64` and `GetBestLimitsTopPower` while the TSETMC market is open, to see the "open market" response shape (only "closed" has been observed).
2. Decide whether to also poll `GetDerivativeFreePowerMarketAtGlance`/`GetDerivativeGreenPowerMarketAtGlance` for Green/Free per-contract data (Power is already wired in).

Closed out, no further action needed:
- ~~Capture the request body for `POST /Report/GetPowerMarketMonthlyPrice`~~ — done; implemented as the historical backfill pipeline (see above).
- ~~Fix the Persian-text encoding issue on `GetDerivativePowerMarketAtGlance`~~ — investigated and found to be a false alarm (console display artifact, not a real bug); now wired into `IEENewCollector`.
- ~~Inspect `oldsite.iee.ir`'s actual page content~~ — done; confirmed to be a stale mirror of the new site hitting the same API, not a distinct source. No collector needed.
