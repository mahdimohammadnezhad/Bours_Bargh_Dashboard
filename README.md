# Iranian Electricity Market Intelligence Dashboard

A real-time market-intelligence dashboard for Iran's electricity market: collects data from TSETMC (Energy Exchange) and the Iran Energy Exchange (IEE), stores it as time-series history, and — as later phases land — analyzes it for decision support. See `docs/ARCHITECTURE.md` for the full system design and `docs/DATA_SOURCES.md` for exactly what is and isn't known about the upstream data sources.

## Read this first: current data-source status

**TSETMC and IEE (new site) are VERIFIED, live, and producing real data** — endpoints were found by downloading each site's production JS bundle and reading its own API client source (not guessed), then confirmed with real HTTP calls. `TSETMCCollector` polls `GET cdn.tsetmc.com/api/Energy/GetPowerOverview/64` (market-wide aggregate: traded value, transaction count, market state). `IEENewCollector` polls `webapi.iee.ir` for per-period/per-submarket trade summaries, a live Free-market snapshot, and a real per-contract trade board (448 electricity contracts with price/volume, confirmed live). Full endpoint list, sample responses, and unit-conversion caveats: `docs/DATA_SOURCES.md`.

**IEE (old site)** was investigated and found to be a stale, older build of the exact same React app as the new site, calling the exact same `webapi.iee.ir` API — not a distinct data source. `IEEOldCollector` stays an intentional stub (`not_configured`); building a real collector for it would just duplicate `IEENewCollector` against a less-fresh, unreliable mirror.

This environment only reached these sites after the user added them to their VPN's allow-list — direct access was unreliable/blocked before that (see `docs/DATA_SOURCES.md` for that history). If you're running this from a network that can't reach `tsetmc.*`/`iee.ir`, the TSETMC/IEE-new collectors will show `degraded`/`down` rather than fabricated data — that's the project's explicit ground rule against inventing market data, not a bug.

## What's implemented (Phase 1 + 2)

**Phase 1 — data pipeline & live dashboard:**
- `TSETMCCollector` — polls the **verified, live** TSETMC Energy API, with retry, exponential backoff + jitter, circuit breaker, 429/403 handling, and defensive parsing that skips bad records instead of crashing.
- `IEENewCollector` — polls the **verified, live** IEE `webapi.iee.ir` endpoints (trade summaries + Free-market snapshot).
- `IEEOldCollector` — intentional stub, `not_configured`. Investigated and closed: it's a stale mirror of `IEENewCollector`'s source, not a distinct one - see `docs/DATA_SOURCES.md`.
- PostgreSQL/TimescaleDB schema (Alembic-migrated) for sources, instruments, quotes, collector logs, and health.
- Redis cache for the latest snapshot (degrades to DB-only if Redis is down — never a hard dependency).
- FastAPI REST API + `/ws/market` WebSocket that pushes only changed data.
- Next.js/TypeScript/Tailwind dashboard: header with connection/market status, KPI cards, live price/volume chart, latest-quotes table, and a Data Health page — all reading real state (including "no data yet" / "source degraded" states), no placeholder numbers.

**Phase 2 — analytics engine** (`backend/app/analytics/`):
- Descriptive + rolling statistics (mean/median/std/CV/percentiles, rolling mean/volatility).
- Four anomaly detectors: rolling z-score, IQR, robust (MAD) z-score, percentile-based.
- Rule-based market regime classification (high/low price, high volatility, high volume, abnormal price), with Observed vs. model-derived vs. interpretation kept as separate fields — never presented as causal.
- Decision-support insight generation (e.g. "current price is in the 92nd percentile...") traced to real computed evidence, never templated text.
- Wired into `GET /api/analytics/overview` and `/api/analytics/anomalies`, and a matching Analytics UI tab with an instrument picker. Both return `status: "insufficient_data"` (200, not fabricated numbers) until an instrument has at least 20 stored observations — which won't happen until a collector is verified against a real endpoint (see above).

Tests for collectors, API endpoints, and the full analytics module (stats/anomalies/regime/decision-support, unit + DB-backed), all mocked or synthetic — no test depends on a live external site.

**Phase 3: forecast, patterns, recommendations.** These work on the whole power market, not a single instrument: the daily base-load volume-weighted price since 1398 (IEE) plus a national temperature series (Open-Meteo). See `docs/DATA_SOURCES.md`.
- **Forecast** (`app/analytics/forecast.py`):
  - Main output: a 6-month outlook from season (Jalali month), temperature (cooling/heating degrees: the weather forecast for the next 16 days, long-term normals after that), trend and the Nowruz cap reset.
  - Walk-forward validation against "no change" and "linear trend": at 3 months ahead, 12.9% vs 19.3% error and 78% vs 45% correct direction.
  - Also a 14-day view. At that horizon "no change" validated best, so the 14-day view uses that model and says why.
  - 80% ranges come from validation errors. Every model's scores are shown.
  - Every validated model's forecast is served (`models` in `/api/analytics/forecast`). The dashboard defaults to the lowest-error model and lets the user switch, for both the monthly and the 14-day view.
- **Patterns** (`app/analytics/patterns.py`): monthly seasonality vs each year's average, month-to-month transitions, weekday effect, temperature–price bins and correlation, and the 10 most similar past situations with what followed (1/5/20 trading days).
- **Recommendations** (`app/analytics/recommendation.py`): upward / downward / mixed pressure for the next 1–3 months, voted from that evidence. Each item carries its number, threshold, observed vs model label, and a weight taken from its own track record. "Agreement" is evidence consistency, not a probability. Cautions are flagged, and nothing is presented as certain.
- History and temperatures are fetched in the background at startup and refreshed every `FORECAST_REFRESH_HOURS` (default 6).

Not implemented yet: scenario analysis, alerts.

## Project structure

```
backend/            FastAPI app, collectors, DB models, Alembic migrations, tests
frontend/            Next.js dashboard
docs/                DATA_SOURCES.md, ARCHITECTURE.md, TROUBLESHOOTING.md
scripts/             local dev helper scripts (no Docker required)
docker-compose.yml   backend + frontend + TimescaleDB + Redis
.env.example         copy to .env and fill in
```

## Quick start — Docker (recommended)

```bash
cp .env.example .env
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend API docs (Swagger/OpenAPI, auto-generated by FastAPI): http://localhost:8000/docs
- Backend health: http://localhost:8000/api/health/sources

## Quick start — local, no Docker

Requires Python 3.11+ (3.10 and 3.12 also verified) and Node 20+. No database server is needed: set `DATABASE_URL=sqlite+aiosqlite:///./dev.db` in `.env` (path relative to `backend/`) to use a local SQLite file. Redis is optional. For PostgreSQL/TimescaleDB instead, run `docker compose up timescaledb redis` and keep the Postgres URL.

```powershell
cp .env.example .env
# edit .env: DATABASE_URL (SQLite line above, or your Postgres), REDIS_URL optional

.\scripts\dev_backend.ps1    # installs deps, runs migrations, starts uvicorn --reload on :8000
.\scripts\dev_frontend.ps1   # installs deps, starts next dev on :3000
```

The backend reads the repo-root `.env` even though it runs from `backend/`. If `backend\.venv` was created on another computer it won't start here; see `docs/TROUBLESHOOTING.md`.

## Running tests

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```

All 48+ backend tests run without any external network or database dependency (SQLite in-memory + mocked HTTP via `respx`).

## Database migrations

```powershell
cd backend
.venv\Scripts\python.exe -m alembic upgrade head      # apply
.venv\Scripts\python.exe -m alembic revision -m "..."  # new migration (hand-write ops; no live DB needed for autogenerate in this environment)
```

## API surface

| Endpoint | Description |
|---|---|
| `GET /api/health/live` | liveness probe |
| `GET /api/health/sources` | per-collector health (status, last success, errors, latency) |
| `GET /api/market/status` | overall session status + all source health |
| `GET /api/market/quotes` | latest quote per (source, instrument) |
| `GET /api/market/instruments` | known canonical instruments |
| `GET /api/history/prices?source_id=&symbol=&start=&end=` | time-series query |
| `GET /api/analytics/overview?source_id=&symbol=&lookback_days=` | descriptive stats, regime, decision-support insights (Phase 2) |
| `GET /api/analytics/anomalies?source_id=&symbol=&lookback_days=` | anomaly detection results (Phase 2) |
| `GET /api/analytics/forecast` | 6-month outlook + 14-day view for the power market, with walk-forward validation of every model |
| `GET /api/analytics/patterns` | seasonality, transitions, weekday, temperature–price, historical analogues |
| `GET /api/analytics/recommendations` | evidence-backed 1–3 month signal with per-item evidence and cautions |
| `WS /ws/market` | full snapshot on connect, diffs thereafter |

Full interactive docs at `/docs` once the backend is running.

## Deployment notes

- Set real secrets via environment variables / your platform's secret manager — never commit `.env`.
- `CORS_ORIGINS` must include your deployed frontend's origin.
- The backend container runs `alembic upgrade head` before starting `uvicorn` (see `backend/Dockerfile`) — migrations are applied automatically on deploy.
- TimescaleDB is opt-in: if your Postgres doesn't have the extension, the app still works with plain tables (see `docs/ARCHITECTURE.md` § Database).
- Nothing in this system depends on IP rotation, proxy pools, or bypassing access controls — see `docs/DATA_SOURCES.md`/`docs/ARCHITECTURE.md` for the polling/backoff strategy used instead, per the project's own ground rules.

## Troubleshooting

See `docs/TROUBLESHOOTING.md`.

## Contributing real endpoint data

The single highest-value contribution right now is verifying the data sources from a network that can reach them — see "How to help verify" in `docs/DATA_SOURCES.md`.
