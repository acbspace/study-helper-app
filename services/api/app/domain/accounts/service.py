"""Account lifecycle.

Email/password is the development-friendly path; Google and Apple slot in as additional
`auth_provider` values against the same user record, so adding them later changes this
service and not the schema (docs/architecture/SECURITY.md).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.clock import ensure_utc
from app.core.config import Settings
from app.core.errors import AppError, ConflictError, ErrorCode
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.enums import AuthProvider
from app.models.user import RefreshToken, User, UserProfile, UserSettings


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"


class AccountService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    # ------------------------------------------------------------------ lookups

    async def get_user(self, user_id: uuid.UUID) -> User | None:
        result = await self._db.execute(
            select(User)
            .options(selectinload(User.profile), selectinload(User.settings))
            .where(User.id == user_id, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def _find_by_email(self, email: str) -> User | None:
        result = await self._db.execute(
            select(User)
            .options(selectinload(User.profile), selectinload(User.settings))
            .where(func.lower(User.email) == email.strip().lower(), User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def _username_taken(self, username: str) -> bool:
        result = await self._db.execute(
            select(UserProfile.id).where(func.lower(UserProfile.username) == username.lower())
        )
        return result.first() is not None

    # ------------------------------------------------------------------ registration

    async def register(
        self,
        *,
        email: str,
        password: str,
        username: str,
        display_name: str | None = None,
        timezone: str = "UTC",
        now: datetime,
        study_category: str = "general_productivity",
        daily_goal_minutes: int = 180,
        weekly_goal_minutes: int = 900,
    ) -> tuple[User, TokenPair]:
        normalized_email = email.strip().lower()
        normalized_username = username.strip()

        if await self._find_by_email(normalized_email) is not None:
            raise ConflictError(
                ErrorCode.EMAIL_ALREADY_REGISTERED, "That email is already registered."
            )
        if await self._username_taken(normalized_username):
            raise ConflictError(ErrorCode.USERNAME_TAKEN, "That username is taken.")

        user = User(
            email=normalized_email,
            password_hash=hash_password(password),
            auth_provider=AuthProvider.EMAIL.value,
            is_active=True,
        )
        user.profile = UserProfile(
            username=normalized_username,
            display_name=(display_name or normalized_username).strip(),
            study_category=study_category,
        )
        user.settings = UserSettings(
            timezone=timezone,
            daily_goal_minutes=daily_goal_minutes,
            weekly_goal_minutes=weekly_goal_minutes,
        )
        self._db.add(user)
        try:
            await self._db.commit()
        except IntegrityError as exc:
            await self._db.rollback()
            # Lost a race on the email or username unique index.
            raise ConflictError(
                ErrorCode.EMAIL_ALREADY_REGISTERED,
                "That email or username is already registered.",
            ) from exc

        await self._db.refresh(user, attribute_names=["profile", "settings"])
        tokens = await self.issue_tokens(user, now=now)
        return user, tokens

    # ------------------------------------------------------------------ login

    async def login(self, *, email: str, password: str, now: datetime) -> tuple[User, TokenPair]:
        user = await self._find_by_email(email)
        # Same error for unknown email and wrong password: no account enumeration.
        invalid = AppError(
            ErrorCode.INVALID_CREDENTIALS, "Email or password is incorrect.", status_code=401
        )
        if user is None or not user.is_active or user.password_hash is None:
            raise invalid
        if not verify_password(password, user.password_hash):
            raise invalid

        tokens = await self.issue_tokens(user, now=now)
        return user, tokens

    async def issue_tokens(
        self, user: User, *, now: datetime, family_id: uuid.UUID | None = None
    ) -> TokenPair:
        access_token, expires_in = create_access_token(self._settings, user.id, now=now)
        refresh_value = generate_refresh_token()
        record = RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_value),
            family_id=family_id or uuid.uuid4(),
            expires_at=ensure_utc(now) + timedelta(days=self._settings.refresh_token_ttl_days),
        )
        self._db.add(record)
        await self._db.commit()
        return TokenPair(
            access_token=access_token, refresh_token=refresh_value, expires_in=expires_in
        )

    async def refresh(self, *, refresh_token: str, now: datetime) -> TokenPair:
        """Rotate a refresh token, revoking the family if a used token reappears."""
        token_hash = hash_refresh_token(refresh_token)
        result = await self._db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        record = result.scalar_one_or_none()
        invalid = AppError(ErrorCode.NOT_AUTHENTICATED, "Invalid refresh token.", status_code=401)
        if record is None:
            raise invalid

        moment = ensure_utc(now)
        if record.revoked_at is not None:
            # Reuse of a rotated token means it leaked: kill the whole family.
            await self._revoke_family(record.family_id, now=moment)
            await self._db.commit()
            raise AppError(
                ErrorCode.NOT_AUTHENTICATED,
                "This session has been revoked. Please sign in again.",
                status_code=401,
            )
        if ensure_utc(record.expires_at) <= moment:
            raise AppError(ErrorCode.TOKEN_EXPIRED, "Refresh token has expired.", status_code=401)

        user = await self.get_user(record.user_id)
        if user is None or not user.is_active:
            raise invalid

        record.revoked_at = moment
        new_value = generate_refresh_token()
        replacement = RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(new_value),
            family_id=record.family_id,
            expires_at=moment + timedelta(days=self._settings.refresh_token_ttl_days),
        )
        self._db.add(replacement)
        await self._db.flush()
        record.replaced_by_id = replacement.id

        access_token, expires_in = create_access_token(self._settings, user.id, now=moment)
        await self._db.commit()
        return TokenPair(access_token=access_token, refresh_token=new_value, expires_in=expires_in)

    async def logout(self, *, refresh_token: str, now: datetime) -> None:
        token_hash = hash_refresh_token(refresh_token)
        result = await self._db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        record = result.scalar_one_or_none()
        if record is not None:
            await self._revoke_family(record.family_id, now=ensure_utc(now))
            await self._db.commit()

    async def _revoke_family(self, family_id: uuid.UUID, *, now: datetime) -> None:
        result = await self._db.execute(
            select(RefreshToken).where(
                RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None)
            )
        )
        for token in result.scalars().all():
            token.revoked_at = now

    # ------------------------------------------------------------------ profile

    async def update_profile(
        self,
        *,
        user: User,
        display_name: str | None = None,
        username: str | None = None,
        avatar_url: str | None = None,
        country_code: str | None = None,
        study_category: str | None = None,
        bio: str | None = None,
    ) -> User:
        profile = user.profile
        if username is not None and username.lower() != profile.username.lower():
            if await self._username_taken(username):
                raise ConflictError(ErrorCode.USERNAME_TAKEN, "That username is taken.")
            profile.username = username.strip()
        if display_name is not None:
            profile.display_name = display_name.strip()
        if avatar_url is not None:
            profile.avatar_url = avatar_url
        if country_code is not None:
            profile.country_code = country_code.upper()
        if study_category is not None:
            profile.study_category = study_category
        if bio is not None:
            profile.bio = bio

        await self._db.commit()
        await self._db.refresh(user, attribute_names=["profile", "settings"])
        return user

    async def update_settings(
        self,
        *,
        user: User,
        expected_version: int | None = None,
        **changes: object,
    ) -> User:
        """Patch settings with optional optimistic concurrency.

        Two devices editing goals simultaneously would otherwise silently overwrite each
        other; sending `expected_version` makes the loser fail loudly instead.
        """
        settings = user.settings
        if expected_version is not None and expected_version != settings.version:
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT,
                "These settings were changed on another device.",
                current_version=settings.version,
            )

        for field_name, value in changes.items():
            if value is None or not hasattr(settings, field_name):
                continue
            setattr(settings, field_name, value)

        settings.version += 1
        await self._db.commit()
        await self._db.refresh(user, attribute_names=["profile", "settings"])
        return user
