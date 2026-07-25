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

    # How long a password-reset token stays usable. Short, because it is emailed in clear.
    password_reset_ttl_minutes: int = Field(default=30, alias="PASSWORD_RESET_TTL_MINUTES")

    cors_origins: list[str] = Field(default_factory=list, alias="CORS_ORIGINS")
    # Host allowlist for TrustedHostMiddleware. Empty means "accept any Host", which is only
    # safe locally; the production validator below refuses to boot without it.
    allowed_hosts: list[str] = Field(default_factory=list, alias="ALLOWED_HOSTS")

    # Domain for the refresh cookie used by browser clients. Its *name* is a constant
    # (`app.api.v1.auth.REFRESH_COOKIE`) rather than a setting, because FastAPI binds cookie
    # parameters by a static alias — a configurable name would read as supported and then
    # silently fail to be parsed.
    refresh_cookie_domain: str | None = Field(default=None, alias="REFRESH_COOKIE_DOMAIN")

    # Transport hardening.
    hsts_max_age_seconds: int = Field(default=63_072_000, alias="HSTS_MAX_AGE_SECONDS")
    # A sync batch after a long offline stretch is the largest legitimate body; 2 MiB leaves
    # generous headroom over that while still bounding what one request can allocate.
    max_request_bytes: int = Field(default=2 * 1024 * 1024, alias="MAX_REQUEST_BYTES")
    # How many reverse proxies sit in front of this app. The client IP is read that many
    # hops from the right of X-Forwarded-For; anything further left is caller-supplied and
    # must never be trusted. 0 means "no proxy", so the header is ignored entirely.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=8, alias="TRUSTED_PROXY_HOPS")

    rate_limit_enabled: bool = Field(default=False, alias="RATE_LIMIT_ENABLED")
    login_attempts_per_minute: int = Field(default=10, alias="LOGIN_ATTEMPTS_PER_MINUTE")
    # Registration and password resets are hourly rather than per-minute: both are rare for
    # a real user and expensive when automated (account spam, mailbox flooding).
    registrations_per_hour: int = Field(default=5, alias="REGISTRATIONS_PER_HOUR")
    password_resets_per_hour: int = Field(default=5, alias="PASSWORD_RESETS_PER_HOUR")
    # Refresh is legitimately frequent — every access-token expiry across every device — but
    # not this frequent; the ceiling exists to stop token grinding.
    refresh_attempts_per_minute: int = Field(default=30, alias="REFRESH_ATTEMPTS_PER_MINUTE")
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
    def _require_safe_deployed_configuration(self) -> Settings:
        """Refuse to boot a deployed environment in an insecure configuration.

        Every check here guards something that fails *silently* if left wrong: a default
        signing key still issues valid-looking tokens, and a disabled rate limiter still
        serves traffic. Refusing to start is the only way those become visible before an
        incident does. Local and test runs stay convenient.
        """
        if self.environment in (Environment.LOCAL, Environment.TEST):
            return self

        if self.jwt_secret == Settings.model_fields["jwt_secret"].default:
            raise ValueError("JWT_SECRET must be set to a unique value outside local/test.")
        if len(self.jwt_secret) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters.")
        if self.device_hash_salt == Settings.model_fields["device_hash_salt"].default:
            raise ValueError("DEVICE_HASH_SALT must be set outside local/test.")
        # A deployment that forgets RATE_LIMIT_ENABLED would otherwise run with no brute
        # force protection at all, and nothing in its behaviour would say so.
        if not self.rate_limit_enabled:
            raise ValueError("RATE_LIMIT_ENABLED must be true outside local/test.")
        if not self.allowed_hosts:
            raise ValueError("ALLOWED_HOSTS must list the hostnames this API serves.")
        return self

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _split_list(cls, value: object) -> object:
        """Accept both a JSON array and a comma-separated string from the environment."""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                return value
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def is_deployed(self) -> bool:
        """Staging and production: TLS-terminated, internet-reachable, cookies must be Secure."""
        return self.environment in (Environment.STAGING, Environment.PRODUCTION)

    @property
    def docs_enabled(self) -> bool:
        return not self.is_production


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
