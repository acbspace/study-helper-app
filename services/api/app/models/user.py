"""Identity, profile, settings, devices, and refresh tokens."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UtcDateTime, UuidType
from app.models.enums import AuthProvider

if TYPE_CHECKING:
    from app.models.study import Subject


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_provider: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AuthProvider.EMAIL.value
    )
    provider_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Moderators see the report queue and can action content. Set out-of-band, never via a
    # public endpoint — there is no "become admin" request anywhere in the API.
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    profile: Mapped[UserProfile] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    settings: Mapped[UserSettings] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    subjects: Mapped[list[Subject]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Case-insensitive uniqueness without depending on PostgreSQL citext.
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
        Index(
            "uq_users_provider_subject",
            "auth_provider",
            "provider_subject",
            unique=True,
            sqlite_where=text("provider_subject IS NOT NULL"),
            postgresql_where=text("provider_subject IS NOT NULL"),
        ),
        CheckConstraint(
            "(auth_provider = 'email' AND password_hash IS NOT NULL)"
            " OR (auth_provider <> 'email' AND provider_subject IS NOT NULL)",
            name="ck_users_credential_present",
        ),
    )


class UserProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    username: Mapped[str] = mapped_column(String(30), nullable=False)
    display_name: Mapped[str] = mapped_column(String(50), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    study_category: Mapped[str] = mapped_column(
        String(64), nullable=False, default="general_productivity"
    )
    bio: Mapped[str | None] = mapped_column(String(280), nullable=True)

    user: Mapped[User] = relationship(back_populates="profile")

    __table_args__ = (
        Index("uq_user_profiles_username_lower", text("lower(username)"), unique=True),
    )


class UserSettings(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    daily_goal_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    weekly_goal_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    # Bitmask: Monday = 1 << 0 … Sunday = 1 << 6. Default = weekdays.
    scheduled_study_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0b0011111)
    pomodoro_focus_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    pomodoro_break_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    privacy_show_subject: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    privacy_show_presence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    user: Mapped[User] = relationship(back_populates="settings")

    __table_args__ = (
        CheckConstraint("daily_goal_minutes BETWEEN 0 AND 1440", name="ck_daily_goal_range"),
        CheckConstraint("weekly_goal_minutes BETWEEN 0 AND 10080", name="ck_weekly_goal_range"),
        CheckConstraint("scheduled_study_days BETWEEN 0 AND 127", name="ck_scheduled_days_bitmask"),
        CheckConstraint("pomodoro_focus_minutes BETWEEN 1 AND 180", name="ck_pomodoro_focus_range"),
        CheckConstraint("pomodoro_break_minutes BETWEEN 1 AND 60", name="ck_pomodoro_break_range"),
    )


class Device(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "devices"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    push_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "device_hash", name="uq_devices_user_hash"),)


class RefreshToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Opaque refresh tokens stored hashed, rotated on use, with family revocation."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UuidType, nullable=False, index=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(UuidType, nullable=True)
