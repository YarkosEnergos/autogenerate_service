from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/generation"
    webhook_secret: str = "dev-secret"
    provider_urls: dict[str, str] = {
        "alpha": "http://localhost:9001",
        "beta": "http://localhost:9002",
    }
    public_base_url: str = "http://localhost:8000"
    provider_timeout: float = 60.0
    provider_http_timeout: float = 5.0
    watchdog_enabled: bool = True
    watchdog_interval: float = 1.0
    max_active_tasks: int = 3
    ledger_history_limit: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
