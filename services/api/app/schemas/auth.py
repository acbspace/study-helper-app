"""Authentication and account contracts."""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import ResponseModel, StrictModel

Username = Annotated[str, Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_.]+$")]
Password = Annotated[str, Field(min_length=8, max_length=128)]


class RegisterRequest(StrictModel):
    email: EmailStr
    password: Password
    username: Username
    display_name: str | None = Field(default=None, max_length=50)
    timezone: str = Field(default="UTC", max_length=64)
    study_category: str = Field(default="general_productivity", max_length=64)
    daily_goal_minutes: int = Field(default=180, ge=0, le=1440)
    weekly_goal_minutes: int = Field(default=900, ge=0, le=10080)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        """Reject unknown zones at the edge so stored data is always resolvable."""
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown time zone: {value}") from exc
        return value


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(StrictModel):
    # Optional because browser clients send the token as an httpOnly cookie instead, so it
    # is never readable from JavaScript. Native clients keep sending it in the body.
    refresh_token: str | None = Field(default=None, min_length=1, max_length=512)


class ChangePasswordRequest(StrictModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: Password


class ForgotPasswordRequest(StrictModel):
    email: EmailStr


class ResetPasswordRequest(StrictModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: Password


class TokenResponse(ResponseModel):
    access_token: str
    # Null when the caller asked for the cookie transport: the refresh token was set as an
    # httpOnly cookie instead, so returning it here too would hand it straight back to
    # JavaScript and undo the point of the cookie.
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_in: int


class ProfileResponse(ResponseModel):
    username: str
    display_name: str
    avatar_url: str | None = None
    country_code: str | None = None
    study_category: str
    bio: str | None = None


class SettingsResponse(ResponseModel):
    timezone: str
    language: str
    daily_goal_minutes: int
    weekly_goal_minutes: int
    scheduled_study_days: int
    pomodoro_focus_minutes: int
    pomodoro_break_minutes: int
    privacy_show_subject: bool
    privacy_show_presence: bool
    notifications_enabled: bool
    version: int


class MeResponse(ResponseModel):
    id: uuid.UUID
    email: str
    profile: ProfileResponse
    settings: SettingsResponse


class AuthResponse(ResponseModel):
    user: MeResponse
    tokens: TokenResponse


class UpdateProfileRequest(StrictModel):
    username: Username | None = None
    display_name: str | None = Field(default=None, max_length=50)
    avatar_url: str | None = Field(default=None, max_length=500)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    study_category: str | None = Field(default=None, max_length=64)
    bio: str | None = Field(default=None, max_length=280)


class UpdateSettingsRequest(StrictModel):
    expected_version: int | None = Field(default=None, ge=1)
    timezone: str | None = Field(default=None, max_length=64)
    language: str | None = Field(default=None, max_length=8)
    daily_goal_minutes: int | None = Field(default=None, ge=0, le=1440)
    weekly_goal_minutes: int | None = Field(default=None, ge=0, le=10080)
    scheduled_study_days: int | None = Field(default=None, ge=0, le=127)
    pomodoro_focus_minutes: int | None = Field(default=None, ge=1, le=180)
    pomodoro_break_minutes: int | None = Field(default=None, ge=1, le=60)
    privacy_show_subject: bool | None = None
    privacy_show_presence: bool | None = None
    notifications_enabled: bool | None = None

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown time zone: {value}") from exc
        return value
