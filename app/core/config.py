"""Application settings loaded from environment variables."""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for API, integrations, and background processing."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    app_env: str = Field(default="local", alias="APP_ENV")
    database_url: str = Field(alias="DATABASE_URL")

    jwt_secret: str = Field(alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(
        default=60,
        alias="ACCESS_TOKEN_EXPIRE_MINUTES",
    )
    oauth_token_encryption_key: str = Field(alias="OAUTH_TOKEN_ENCRYPTION_KEY")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

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

    analytics_cron_interval_minutes: int = Field(
        default=5,
        alias="ANALYTICS_CRON_INTERVAL_MINUTES",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance for dependency injection."""

    return Settings()

