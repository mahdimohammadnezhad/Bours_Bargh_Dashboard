from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[2]

# The documented setup keeps a single .env at the repo root (see
# .env.example / README), but scripts/dev_backend.ps1 starts uvicorn from
# backend/ - a cwd-relative ".env" silently missed it, so the backend ran
# on built-in defaults (Postgres on localhost) regardless of what .env
# said. Resolve both locations from this file instead; later entries take
# priority, and real environment variables (e.g. docker-compose's) still
# override both.
_ENV_FILES = (_BACKEND_DIR.parent / ".env", _BACKEND_DIR / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILES, env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Iranian Electricity Market Intelligence Dashboard"
    ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/electricity_market"
    REDIS_URL: str = "redis://localhost:6379/0"

    TSETMC_BASE_URL: str = "https://cdn.tsetmc.com/api"
    # webapi.iee.ir is the real API host used by the newsite.iee.ir frontend
    # (confirmed by inspecting its JS bundle - see docs/DATA_SOURCES.md).
    # newsite.iee.ir itself only serves the SPA shell, not JSON.
    IEE_NEW_BASE_URL: str = "https://webapi.iee.ir/api"
    IEE_OLD_BASE_URL: str = "https://oldsite.iee.ir"

    POLL_INTERVAL_ACTIVE: float = 5.0
    POLL_INTERVAL_IDLE: float = 60.0
    # Floor for IEE specifically: its WAF answered ~1-in-8 cycles with 403
    # when polled every 5s (3 requests/cycle) on 2026-10-11. TSETMC showed
    # no such throttling and keeps POLL_INTERVAL_ACTIVE.
    IEE_MIN_POLL_INTERVAL: float = 15.0
    MARKET_ACTIVE_HOURS_START: int = 9
    MARKET_ACTIVE_HOURS_END: int = 15

    HTTP_TIMEOUT_SECONDS: float = 10.0
    MAX_RETRIES: int = 3
    BACKOFF_BASE_SECONDS: float = 1.0
    BACKOFF_MAX_SECONDS: float = 300.0
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    CIRCUIT_BREAKER_COOLDOWN_SECONDS: float = 120.0

    # Daily temperatures for the price forecast (Open-Meteo: free, no key).
    # Archive = observed history (lags ~5 days); forecast = next 16 days.
    WEATHER_ARCHIVE_URL: str = "https://archive-api.open-meteo.com/v1/archive"
    WEATHER_FORECAST_URL: str = "https://api.open-meteo.com/v1/forecast"
    # How often the price history + weather behind the forecast are refreshed.
    FORECAST_REFRESH_HOURS: float = 6.0

    CACHE_TTL_SECONDS: int = 30
    STALE_AFTER_SECONDS: int = 90

    CORS_ORIGINS: str = "http://localhost:3000"
    # Our own API's rate limit (brief §32), not the upstream collectors' -
    # those are governed separately by POLL_INTERVAL_*. 0 disables it.
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 120

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
