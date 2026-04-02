"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for API, integrations, and background processing."""

    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        case_sensitive=True,
    )

    app_env: str = Field(default="local", alias="APP_ENV")
    database_url: str = Field(alias="DATABASE_URL")
    db_pool_size: int = Field(default=20, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=40, alias="DB_MAX_OVERFLOW")
    db_pool_timeout_seconds: int = Field(default=30, alias="DB_POOL_TIMEOUT_SECONDS")

    jwt_secret: str = Field(alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(
        default=60,
        alias="ACCESS_TOKEN_EXPIRE_MINUTES",
    )
    oauth_token_encryption_key: str = Field(alias="OAUTH_TOKEN_ENCRYPTION_KEY")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_enabled: bool = Field(default=True, alias="REDIS_ENABLED")
    redis_short_code_ttl_seconds: int = Field(
        default=300,
        alias="REDIS_SHORT_CODE_TTL_SECONDS",
    )

    google_analytics_measurement_id: Optional[str] = Field(
        default=None,
        alias="GOOGLE_ANALYTICS_MEASUREMENT_ID",
    )
    google_analytics_api_secret: Optional[str] = Field(
        default=None,
        alias="GOOGLE_ANALYTICS_API_SECRET",
    )

    google_client_id: Optional[str] = Field(default=None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: Optional[str] = Field(
        default=None,
        alias="GOOGLE_CLIENT_SECRET",
    )
    google_redirect_uri: Optional[str] = Field(
        default=None,
        alias="GOOGLE_REDIRECT_URI",
    )

    queue_backend: str = Field(default="memory", alias="QUEUE_BACKEND")
    queue_url: Optional[str] = Field(default=None, alias="QUEUE_URL")
    dlq_name: str = Field(default="scan_logs_dlq", alias="DLQ_NAME")
    scan_log_queue_name: str = Field(
        default="scan_logs",
        alias="SCAN_LOG_QUEUE_NAME",
    )
    queue_max_retry_attempts: int = Field(default=5, alias="QUEUE_MAX_RETRY_ATTEMPTS")
    queue_visibility_timeout_seconds: int = Field(
        default=30,
        alias="QUEUE_VISIBILITY_TIMEOUT_SECONDS",
    )

    analytics_cron_interval_minutes: int = Field(
        default=5,
        alias="ANALYTICS_CRON_INTERVAL_MINUTES",
    )

    cors_allow_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        alias="CORS_ALLOW_ORIGINS",
    )
    cors_allow_credentials: bool = Field(default=True, alias="CORS_ALLOW_CREDENTIALS")
    cors_allow_methods: list[str] = Field(default=["*"], alias="CORS_ALLOW_METHODS")
    cors_allow_headers: list[str] = Field(default=["*"], alias="CORS_ALLOW_HEADERS")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance for dependency injection."""

    return Settings()

