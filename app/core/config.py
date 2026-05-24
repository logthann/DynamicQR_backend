"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
LOCAL_ENV_NAMES = {"local", "dev", "development", "test", "testing"}


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

    service_jwt_secret: str = Field(
        default="local-service-secret-change-me",
        alias="SERVICE_JWT_SECRET",
    )
    service_jwt_algorithm: str = Field(default="HS256", alias="SERVICE_JWT_ALGORITHM")
    service_jwt_issuer: str = Field(default="dynamicqr-internal", alias="SERVICE_JWT_ISSUER")
    service_jwt_audience: str = Field(default="dynamicqr-tracking", alias="SERVICE_JWT_AUDIENCE")

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

    queue_backend: str = Field(default="auto", alias="QUEUE_BACKEND")
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

    @field_validator(
        "cors_allow_origins",
        "cors_allow_methods",
        "cors_allow_headers",
        mode="before",
    )
    @classmethod
    def _split_csv_settings(cls, value: object) -> object:
        """Support comma-separated env values for list settings."""

        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _validate_deploy_safe_urls(self) -> "Settings":
        """Prevent non-local deployments from accidentally using localhost URLs."""

        if self.app_env.lower().strip() in LOCAL_ENV_NAMES:
            return self

        self._reject_local_url("GOOGLE_REDIRECT_URI", self.google_redirect_uri)
        for origin in self.cors_allow_origins:
            self._reject_local_url("CORS_ALLOW_ORIGINS", origin)
        return self

    @staticmethod
    def _reject_local_url(setting_name: str, value: str | None) -> None:
        if not value:
            return

        hostname = urlparse(value).hostname
        if hostname in LOCAL_HOSTNAMES:
            raise ValueError(
                f"{setting_name} must not point to localhost outside local/test environments",
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance for dependency injection."""

    return Settings()
