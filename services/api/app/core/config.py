"""Environment-driven configuration.

Every deployable environment (local, test, staging, production) configures the same
settings object; nothing is hardcoded per environment and no secret has a usable default.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = Field(default=Environment.LOCAL, alias="STUDY_ENV")

    database_url: str = Field(
        default="sqlite+aiosqlite:///./study_league.db",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    jwt_secret: str = Field(default="local-dev-secret-change-me", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_issuer: str = Field(default="study-league", alias="JWT_ISSUER")
    jwt_audience: str = Field(default="study-league-app", alias="JWT_AUDIENCE")
    access_token_ttl_minutes: int = Field(default=30, alias="ACCESS_TOKEN_TTL_MINUTES")
    refresh_token_ttl_days: int = Field(default=30, alias="REFRESH_TOKEN_TTL_DAYS")
    # Short-lived ticket minted over REST and presented as the WebSocket query param, so a
    # long-lived access token never travels in a URL.
    ws_ticket_ttl_seconds: int = Field(default=60, alias="WS_TICKET_TTL_SECONDS")

    device_hash_salt: str = Field(default="local-device-salt", alias="DEVICE_HASH_SALT")

    cors_origins: list[str] = Field(default_factory=list, alias="CORS_ORIGINS")

    rate_limit_enabled: bool = Field(default=False, alias="RATE_LIMIT_ENABLED")
    login_attempts_per_minute: int = Field(default=10, alias="LOGIN_ATTEMPTS_PER_MINUTE")
    # Social writes (friend requests, invites, reactions, reports) share one bucket: the
    # abuse they enable is the same shape, and one dial is easier to tune than six.
    social_writes_per_minute: int = Field(default=60, alias="SOCIAL_WRITES_PER_MINUTE")

    # Session integrity thresholds — configurable, never magic numbers in domain code.
    max_session_hours: float = Field(default=12.0, alias="MAX_SESSION_HOURS")
    max_single_interval_hours: float = Field(default=6.0, alias="MAX_SINGLE_INTERVAL_HOURS")
    max_clock_skew_minutes: float = Field(default=10.0, alias="MAX_CLOCK_SKEW_MINUTES")
    retro_edit_window_hours: float = Field(default=48.0, alias="RETRO_EDIT_WINDOW_HOURS")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @model_validator(mode="after")
    def _require_strong_production_secrets(self) -> Settings:
        """Refuse to boot a deployed environment with a weak or default secret.

        HS256 keys shorter than 32 bytes weaken the signature, and the checked-in default
        is public knowledge. Local and test runs stay convenient.
        """
        if self.environment in (Environment.LOCAL, Environment.TEST):
            return self
        if self.jwt_secret == Settings.model_fields["jwt_secret"].default:
            raise ValueError("JWT_SECRET must be set to a unique value outside local/test.")
        if len(self.jwt_secret) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters.")
        if self.device_hash_salt == Settings.model_fields["device_hash_salt"].default:
            raise ValueError("DEVICE_HASH_SALT must be set outside local/test.")
        return self

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept both a JSON array and a comma-separated string from the environment."""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                return value
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def docs_enabled(self) -> bool:
        return not self.is_production


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
