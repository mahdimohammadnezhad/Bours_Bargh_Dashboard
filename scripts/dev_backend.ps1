# Run the backend API locally without Docker (requires a reachable
# PostgreSQL/TimescaleDB and Redis - see ../.env.example).
Set-Location "$PSScriptRoot\..\backend"
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& ".venv\Scripts\python.exe" -m pip install -q -r requirements-dev.txt
& ".venv\Scripts\python.exe" -m alembic upgrade head
& ".venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
