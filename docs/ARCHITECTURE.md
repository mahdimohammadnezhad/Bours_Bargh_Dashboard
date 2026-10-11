# Architecture — Iranian Electricity Market Intelligence Dashboard

This document describes the system as built in Phase 1 (MVP) and the intended shape of later phases. See `docs/DATA_SOURCES.md` first — the honesty of this whole system depends on that document, not on this one.

## Guiding constraint

The frontend never talks to TSETMC/IEE directly, and no client polls an external site on a fixed short interval "just in case." Only backend collectors talk to external sources, on an adaptive schedule, and everything downstream reads from our own cache/database.

```
TSETMC / IEE  →  Collector (asyncio, retry+backoff+circuit breaker)
              →  Redis (latest snapshot, short TTL)
              →  PostgreSQL/TimescaleDB (append-only history)
              →  FastAPI (REST reads from Redis/DB)
              →  WebSocket (pushes only diffs, on change)
              →  Next.js frontend
```

## Backend layout

```
backend/
  app/
    core/         settings (pydantic-settings), logging setup
    collectors/    one class per source + a manager that runs them as background tasks
    cache/         thin Redis wrapper, degrades to no-op if Redis is unreachable
    database/      async SQLAlchemy engine/session
    models/        SQLAlchemy ORM models (canonical schema)
    schemas/       Pydantic request/response models
    services/      business logic that sits between API routes and models/cache
    websocket/     connection manager + broadcast
    api/           FastAPI routers
    analytics/     placeholder package for Phase 2/3 (empty on purpose in Phase 1)
    main.py        app factory, startup/shutdown wiring
  tests/           pytest, all external calls mocked
```

## Collectors

Each collector (`backend/app/collectors/tsetmc_collector.py`, `iee_new_collector.py`, `iee_old_collector.py`) implements the shared `BaseCollector` contract in `backend/app/collectors/base.py`:

- `fetch()` — makes the HTTP call(s) for one polling cycle.
- `parse(raw)` — turns the raw payload into the canonical `NormalizedQuote` shape. Never throws on a single bad field — logs and skips that field.
- `validate(normalized)` — sanity checks (non-negative price/volume, timestamp not absurdly stale/future) before anything is persisted.
- Per-collector `CollectorState` tracks: last success time, last error, consecutive failures, current backoff interval, circuit-breaker state (`closed` / `open` / `half_open`).

Resilience behavior (per source, independent of the others):

- Exponential backoff with jitter on failure, capped at a max interval.
- Circuit breaker: after N consecutive failures, stop calling the source for a cool-down window and serve the last-known-good cached value with a `stale` flag; periodically send one probe request (`half_open`) to test recovery.
- HTTP 429 → immediately widen the interval and honor `Retry-After` if present.
- HTTP 403 → mark the source `degraded`, stop polling at high frequency, keep a slow background probe.
- Any single collector crashing never takes down the FastAPI process — collectors run as isolated `asyncio.Task`s supervised by the collector manager, which restarts a crashed task with backoff rather than propagating the exception.

`TSETMCCollector` and `IEENewCollector` now call verified, live endpoints (see `DATA_SOURCES.md`). `IEEOldCollector` runs in a `not_configured` state by design, not by omission: investigation showed `oldsite.iee.ir` is a stale build of the same React app as the new site, calling the same `webapi.iee.ir` API - there is no distinct dataset to collect there, so it makes no network calls and reports itself as such via `/api/health/sources`. The rest of the system (cache, DB, API, frontend) treats "not configured" exactly like "temporarily degraded."

## Adaptive polling

`POLL_INTERVAL_ACTIVE` and `POLL_INTERVAL_IDLE` (see `.env.example`) bound the interval; the manager narrows toward the active interval when the source's own data timestamp is advancing between polls, and widens toward the idle interval when consecutive polls return byte-identical payloads (deduplicated by hashing the normalized record, not the raw bytes, so irrelevant fields like server-side render timestamps don't defeat dedup) — this is the "don't store identical records" and "incremental sync if possible" requirement from the brief. Since none of the sources' real incremental/delta support is confirmed yet, this starts as poll-and-diff; if a source turns out to expose a sequence number or `since=` parameter, the collector can switch to true incremental fetch without changing anything upstream of it.

## Database

PostgreSQL, with TimescaleDB extension used opportunistically: at startup, the app attempts `CREATE EXTENSION IF NOT EXISTS timescaledb` and, if it succeeds, converts the time-series tables into hypertables; if the extension isn't available (e.g. plain Postgres in a constrained dev environment) it just runs as regular indexed tables. Nothing in the application code depends on Timescale-specific SQL, so this is a pure performance opt-in.

Core tables (Phase 1 subset of the full schema in the brief — the rest are added as later phases need them, so migrations stay reviewable):

- `data_sources` — one row per collector (`tsetmc`, `iee_new`, `iee_old`), current health snapshot.
- `instruments` — canonical instrument, with `source_instruments` mapping table for per-source identifiers (see the normalization note in `DATA_SOURCES.md`).
- `market_quotes` — the time-series fact table: timestamp, source, instrument, last price, change, % change, volume, value, transaction count, raw payload reference.
- `collector_logs` — structured log of every fetch cycle (start, latency, status, records in/skipped, error).
- `system_health` — periodic snapshot used by `/api/health/sources` and the Data Health page.

Uniqueness/dedup key: `(source_id, source_symbol, observed_at)`, so re-polling the same unchanged tick is an upsert, not a duplicate row.

Migrations: Alembic, in `backend/alembic/`.

## Caching

Redis holds only the latest snapshot per instrument (`quote:{source}:{symbol}`) with a short TTL slightly longer than the active poll interval, plus collector health. The cache is an accelerator, not a source of truth — the database is. If Redis is down, reads fall back to the database and writes just skip the cache step; this is intentional (§30 of the brief: one dependency failing must not take down the app), logged as degraded rather than raised.

## Real-time delivery

`WS /ws/market`: on connect, the server sends one full current snapshot; after that, only diffs (changed fields per instrument) are pushed, generated by the collector manager whenever a poll produces a change. Heartbeat ping/pong every 30s; the frontend reconnects with backoff on drop and treats data older than `STALE_AFTER_SECONDS` as stale in the UI regardless of connection state.

## API surface (Phase 1)

```
GET  /api/health/sources         collector/source health
GET  /api/market/status          overall market/session status
GET  /api/market/instruments     known instruments
GET  /api/market/quotes          latest quotes (from cache, DB fallback)
GET  /api/history/prices         time-series query (date range, instrument)
WS   /ws/market
```

Analytics/anomaly/forecast/recommendation endpoints from the full brief (§26) are deliberately not implemented in Phase 1 — they need real historical data to be honest (§16/§48 explicitly forbid fabricated insights), which doesn't exist yet against unverified sources. Their routers are stubbed to return `501 Not Implemented` with an explanatory message rather than omitted outright, so the frontend's routing/layout for those sections can be built now and wired up in Phase 2/3 without reshaping the app.

## Frontend

Next.js (App Router) + TypeScript + Tailwind CSS. `lightweight-charts` for the price/volume chart (purpose-built for trading-style time-series, not a generic charting kit). Data access:

- Initial load: REST (`/api/market/*`) for first paint.
- Live updates: WebSocket subscription, patched into the same client-side store so REST and WS never disagree about shape.
- Explicit stale/disconnected/error UI states everywhere real-time data is shown (§35/§43 of the brief).

Phase 1 pages: Overview/Real-Time Monitor (merged into one dashboard, since Phase 1 has one data feed), Data Health. The tab shells for Historical/Patterns/Anomalies/Forecast/Recommendations exist in the nav per §37 but render an honest "not available yet — needs Phase 2/3 analytics and verified historical data" placeholder rather than fake charts.

## Known gaps (tracked on purpose, not hidden)

1. This dev environment initially had almost no reliable network route to any of the three sources (VPN/geo-blocking related, not a code issue); the user resolved this by adding the sites to their VPN's allow-list. TSETMC and IEE (new site) are now verified against live responses - endpoints and parameters were read directly out of each site's own production JS bundle rather than guessed - see `DATA_SOURCES.md` for exact paths, params, and sample payloads.
2. `IEEOldCollector` is a deliberate, closed-investigation stub: `oldsite.iee.ir` turned out to be a stale build of the same app as the new site hitting the same API, not a third data source (see `DATA_SOURCES.md`). Nothing is pending here.
3. Cross-source canonical unit reconciliation (§40 of the brief) has real data to work from now - `DATA_SOURCES.md` documents one confirmed unit mismatch (IEE's `tradedValue` is millions of Rials on one endpoint and full Rials on another) - but a general reconciliation layer across all fields/sources is not yet built.
4. Analytics (`app/analytics/`, Phase 2) is implemented and tested: descriptive/rolling stats, four anomaly detectors (rolling z-score, IQR, robust/MAD z-score, percentile), rule-based regime classification, and decision-support insight generation, wired into `GET /api/analytics/overview` and `/anomalies`. It runs honestly against whatever is in `market_quotes` - real requests return `status: "insufficient_data"` rather than fabricated numbers until enough history exists (see §47 of the brief), which it now does. `/patterns` (historical analogues) and `/recommendations` (evidence-backed recommendation engine) are still Phase 3 stubs: both need a historical-analogue engine that hasn't been built yet.
5. All primary keys are `BigInteger` for Postgres/production headroom, given the `.with_variant(Integer, "sqlite")` in `app/models/market.py` - SQLite only auto-populates an integer PK when the column's DDL affinity is the literal word `INTEGER` (its rowid alias); a plain `BigInteger` renders as `BIGINT` there and never auto-populates. This was a real bug (not just a test-fixture quirk) - it broke real inserts through `market_service.upsert_quote` the first time this app ran against SQLite, not only ORM-direct test inserts. Both paths now work identically on SQLite and Postgres.
6. `market_service.get_latest_quotes()` computes "the latest row per (source, symbol)" with a `ROW_NUMBER() OVER (PARTITION BY ...)` window query, not by taking the N globally-most-recent rows and deduping in Python - the latter silently dropped any symbol that ticks less often than the busiest ones once distinct-symbol count approached N (discovered when IEE's ~450 per-cycle contract quotes crowded out the once-a-month historical backfill entirely). A supporting index (`ix_quote_symbol_observed_desc` - see the Alembic migration `a3f7c9d2e1b4`) keeps that query fast; without it, the same query took several seconds against a table that had grown past ~700k rows in one continuous multi-hour local test run. SQLite is also set to `PRAGMA journal_mode=WAL` (`app/database/session.py`) so a live collector writing every few seconds doesn't block the API's own reads - the default rollback-journal mode let a writer starve every reader for the duration of its transaction, which is exactly what a continuously-polling collector does almost constantly.
7. Historical ingestion (the one item Phase 2 was still missing) is done: `app/services/historical_ingestion.py` backfills IEE's monthly average base-load price (Power/Green/Free) from 1402 onward via `POST /Report/GetPowerMarketMonthlyPrice`, using `jdatetime` for the Jalali→Gregorian conversion the report is keyed by. Runs once automatically on startup if empty (`app/main.py::maybe_run_historical_backfill`, fire-and-forget so it never delays the app becoming ready) and can be re-run manually via `backend/scripts/backfill_historical.py`. Idempotent (upserts by month, never duplicates) - see `docs/DATA_SOURCES.md` for the verified request/response shape.

## Phased roadmap (mirrors §45 of the project brief)

- **Phase 1 (done):** source discovery, TSETMC/IEE collectors verified against live endpoints, DB (with rate limiting on our own API and a tested WebSocket), real-time API, basic dashboard (now bilingual fa/en).
- **Phase 2 (done):** price/volume analytics, anomaly detection engine, historical ingestion (monthly backfill), and a data explorer UI (`/history` - date range, CSV export).
- **Phase 3 (not started):** historical analogues, decision support beyond the current per-request insights, forecasting, recommendation engine.
- **Phase 4 (not started):** alerts, monitoring, optimization, production hardening.
