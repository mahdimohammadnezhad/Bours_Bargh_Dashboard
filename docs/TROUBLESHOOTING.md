# Troubleshooting

## "TSETMC"/"IEE" sources show `degraded`, `down`, or never go `healthy`

`TSETMCCollector` and `IEENewCollector` call verified endpoints (see `docs/DATA_SOURCES.md`) — if they're not `healthy`, it's a connectivity or upstream-change problem, not an unverified guess. Check, in order:

1. `GET /api/health/sources` — look at `last_error` for the source.
2. Backend logs (`docker compose logs backend` or the terminal running `uvicorn`) — every collector cycle logs its outcome.
3. Can the *host machine* reach the site at all? `curl -I https://cdn.tsetmc.com/` / `curl -I https://webapi.iee.ir/`. If that times out, it's a network/geo-blocking issue, not a bug in this project — both `tsetmc.*` and `iee.ir` are geo/VPN-sensitive; this project's own dev environment needed the sites added to a VPN allow-list before they became reachable (see `docs/DATA_SOURCES.md`).
4. If the host can reach it but the collector still errors, the upstream site has likely changed its endpoint or response shape since this was verified (2026-08-22) — re-run the investigation technique in `docs/DATA_SOURCES.md` (download the site's current JS bundle, grep it for `/api/` paths) rather than guessing a fix, and update `backend/app/collectors/tsetmc_collector.py` / `iee_new_collector.py` to match.

## `iee_old` always reports `not_configured`

This is not a bug and not a gap — it's a deliberate, investigated conclusion. `oldsite.iee.ir` was found to be a stale build of the exact same app as `newsite.iee.ir`, calling the exact same `webapi.iee.ir` API that `IEENewCollector` already polls (see `docs/DATA_SOURCES.md`). There is no separate dataset to implement a collector against, so `IEEOldCollector` stays `not_configured` by design.

## Backend fails to start: database connection errors

- Confirm `DATABASE_URL` in `.env` points at a running PostgreSQL/TimescaleDB instance (`docker compose up timescaledb` on its own to check).
- `init_db()` in `app/database/session.py` deliberately does not crash the app if the DB is unreachable at startup (it logs and continues in a degraded mode) — but every DB-backed endpoint will then fail. Fix the connection and restart.
- `CREATE EXTENSION timescaledb` failing is not fatal and is expected on plain PostgreSQL (e.g. a local dev Postgres without the extension installed) — the app falls back to regular tables automatically.

## Redis connection errors in the logs

Also non-fatal by design (`app/cache/redis_client.py`): the API falls back to reading from PostgreSQL directly. You'll see slightly higher latency and the WebSocket dedup-by-hash still works (state is kept in-process per collector), but nothing crashes. Fix `REDIS_URL` and restart to restore caching.

## WebSocket connects then immediately disconnects / no live updates

- Check `NEXT_PUBLIC_WS_URL` matches the backend's actual host/port.
- Check CORS: `CORS_ORIGINS` in the backend `.env` must include the frontend's origin.
- If quotes never change (e.g. both IEE collectors are `not_configured` and TSETMC can't reach its endpoint), there is nothing to broadcast — the snapshot on connect will be empty, and `/api/health/sources` will show why.

## Running the backend against SQLite (no Docker/Postgres)

`DATABASE_URL=sqlite+aiosqlite:///./dev.db` in the repo-root `.env` is a fully working local setup for a single machine: collectors write, history accumulates, the API/WebSocket/frontend all work. The path is relative to `backend/`, where `scripts/dev_backend.ps1` starts uvicorn. Redis is optional (the cache no-ops without it).

What makes this work, in case something regresses:
- The backend reads the **repo-root** `.env` even though it runs from `backend/` (`app/core/config.py` resolves it from its own location). Before 2026-10-11 it only looked for `backend/.env`, silently ignored the root file, and fell back to built-in defaults (Postgres on localhost).
- SQLite allows one writer at a time, so all write transactions go through one in-process lock (`db_write_lock()` in `app/database/session.py`). Without it, the first collector cycles overlapping the startup backfill failed with `database is locked` and lost those writes.
- SQLite returns timestamps without a timezone; `UTCDateTime` in `app/models/market.py` re-attaches UTC so the browser doesn't read them as local time (they were 3.5 h off in Tehran).

For multi-user or long-running production use, prefer `docker compose up` (TimescaleDB).

## `iee_new` flips between `healthy` and `degraded` with HTTP 403

IEE's API sits behind a web application firewall (it sets a `cookiesession1` cookie) that answers bursts with `403 Forbidden`. At a 5 s poll interval (3 requests per cycle), about 1 in 8 cycles got a 403 on 2026-10-11. The collector treats a 403 as "slow down" and recovers on the next success, so data keeps flowing, just with occasional gaps. `IEE_MIN_POLL_INTERVAL` (default 15 s) sets IEE's own minimum interval, and the startup backfill spaces its requests 2 s apart. If 403s become frequent, raise `IEE_MIN_POLL_INTERVAL` rather than lowering it.

## The backend was moved to another computer / `.venv` won't start

A Python virtualenv is tied to the machine and the Python install it was created with (`backend/.venv/pyvenv.cfg` names the interpreter path). If that path doesn't exist on this machine (e.g. `No Python at 'C:\Users\<someone else>\...'`), recreate it: `python -m venv --clear backend\.venv`, then `backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt`.

## `pip install` / `npm install` fails in this environment

- Backend: use the pinned `backend/requirements.txt` (`requirements-dev.txt` for tests) inside a virtualenv; Python 3.11 target (3.10 also verified working).
- Frontend: Node 20+ required by Next.js; delete `frontend/node_modules` and `frontend/package-lock.json` and reinstall if you hit a broken lockfile after switching Node versions.

## I can reach the sites and want to help fix the collectors

See "How to help verify" at the bottom of `docs/DATA_SOURCES.md` — capture the real requests with DevTools and share the endpoint + one sample JSON response per source. That's the single highest-value contribution to this project right now; everything else (DB schema, API, WebSocket, frontend) is already wired and waiting on real data.
