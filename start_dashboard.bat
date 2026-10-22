@echo off
REM Start the dashboard: backend (API, port 8000) and frontend (port 3000)
REM each in its own window, then open the browser.
REM Keep both windows open while you use the dashboard; close them to stop it.
REM PattN (VPN) must be on so TSETMC / IEE are reachable.

cd /d "%~dp0"
start "Dashboard backend (8000)" powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0scripts\dev_backend.ps1"
start "Dashboard frontend (3000)" powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0scripts\dev_frontend.ps1"

echo Waiting for the dashboard to start...
timeout /t 25 /nobreak >nul
start "" http://localhost:3000
