"""Authentication and account routes.

Two refresh-token transports are supported, chosen by the client with the
`X-Refresh-Transport` header:

* **body** (default) — the token is returned in the response, which is what a native app
  needs so it can put it in the platform keystore.
* **cookie** — the token is set as an httpOnly cookie and omitted from the response body,
  which is what a browser needs so that XSS cannot read it. Anything a page's JavaScript can
  reach, injected JavaScript can exfiltrate; the only refresh token a browser can hold safely
  is one it cannot see.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, Response, status

from app.api.deps import AccountServiceDep, CurrentUser, EmailSenderDep, SettingsDep
from app.api.rate_limit import (
    login_rate_limit,
    password_reset_rate_limit,
    refresh_rate_limit,
    register_rate_limit,
)
from app.core.clock import utc_now
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.domain.accounts.service import TokenPair
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UpdateProfileRequest,
    UpdateSettingsRequest,
)

router = APIRouter(tags=["auth"])

COOKIE_TRANSPORT = "cookie"
REFRESH_COOKIE = "sl_refresh"
RefreshTransport = Annotated[str | None, Header(alias="X-Refresh-Transport")]
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


def _wants_cookie(transport: str | None) -> bool:
    return (transport or "").strip().lower() == COOKIE_TRANSPORT


def _apply_tokens(
    response: Response, settings: Settings, tokens: TokenPair, *, use_cookie: bool
) -> TokenResponse:
    """Return the token payload, moving the refresh token into a cookie when asked."""
    if not use_cookie:
        return TokenResponse.model_validate(tokens)

    response.set_cookie(
        key=REFRESH_COOKIE,
        value=tokens.refresh_token,
        httponly=True,
        # Strict rather than Lax: no third-party page has any reason to trigger a refresh,
        # and this leaves no room for a cross-site request to ride the cookie.
        samesite="strict",
        # Secure would make the cookie undeliverable over plain http://localhost, so it
        # tracks the environment rather than being hardcoded either way.
        secure=settings.is_deployed,
        domain=settings.refresh_cookie_domain,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path="/api/v1/auth",
    )
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=None,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE,
        domain=settings.refresh_cookie_domain,
        path="/api/v1/auth",
    )


def _resolve_refresh_token(body_token: str | None, cookie_token: str | None) -> str:
    token = body_token or cookie_token
    if not token:
        raise AppError(
            ErrorCode.NOT_AUTHENTICATED, "No refresh token was supplied.", status_code=401
        )
    return token


@router.post(
    "/auth/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    dependencies=[Depends(register_rate_limit)],
)
async def register(
    payload: RegisterRequest,
    response: Response,
    accounts: AccountServiceDep,
    settings: SettingsDep,
    transport: RefreshTransport = None,
) -> AuthResponse:
    user, tokens = await accounts.register(
        email=str(payload.email),
        password=payload.password,
        username=payload.username,
        display_name=payload.display_name,
        timezone=payload.timezone,
        study_category=payload.study_category,
        daily_goal_minutes=payload.daily_goal_minutes,
        weekly_goal_minutes=payload.weekly_goal_minutes,
        now=utc_now(),
    )
    return AuthResponse(
        user=MeResponse.model_validate(user),
        tokens=_apply_tokens(response, settings, tokens, use_cookie=_wants_cookie(transport)),
    )


@router.post(
    "/auth/login",
    response_model=AuthResponse,
    summary="Sign in",
    dependencies=[Depends(login_rate_limit)],
)
async def login(
    payload: LoginRequest,
    response: Response,
    accounts: AccountServiceDep,
    settings: SettingsDep,
    transport: RefreshTransport = None,
) -> AuthResponse:
    user, tokens = await accounts.login(
        email=str(payload.email), password=payload.password, now=utc_now()
    )
    return AuthResponse(
        user=MeResponse.model_validate(user),
        tokens=_apply_tokens(response, settings, tokens, use_cookie=_wants_cookie(transport)),
    )


@router.post(
    "/auth/refresh",
    response_model=TokenResponse,
    summary="Rotate tokens",
    dependencies=[Depends(refresh_rate_limit)],
)
async def refresh(
    payload: RefreshRequest,
    response: Response,
    accounts: AccountServiceDep,
    settings: SettingsDep,
    transport: RefreshTransport = None,
    sl_refresh: RefreshCookie = None,
) -> TokenResponse:
    token = _resolve_refresh_token(payload.refresh_token, sl_refresh)
    tokens = await accounts.refresh(refresh_token=token, now=utc_now())
    # A request that arrived by cookie is refreshed back into a cookie, whatever it declared:
    # otherwise the rotated token would be returned in the body and the stale cookie left in
    # place, signing the browser out at the next refresh.
    use_cookie = _wants_cookie(transport) or (payload.refresh_token is None)
    return _apply_tokens(response, settings, tokens, use_cookie=use_cookie)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a session")
async def logout(
    payload: RefreshRequest,
    response: Response,
    accounts: AccountServiceDep,
    settings: SettingsDep,
    sl_refresh: RefreshCookie = None,
) -> None:
    token = payload.refresh_token or sl_refresh
    if token:
        await accounts.logout(refresh_token=token, now=utc_now())
    # Cleared unconditionally: a logout that leaves the cookie behind looks like it failed.
    _clear_refresh_cookie(response, settings)


@router.post(
    "/auth/change-password",
    response_model=TokenResponse,
    summary="Change your password",
    dependencies=[Depends(login_rate_limit)],
)
async def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    user: CurrentUser,
    accounts: AccountServiceDep,
    settings: SettingsDep,
    transport: RefreshTransport = None,
) -> TokenResponse:
    """Every other session is revoked, so the caller is re-issued one fresh token pair."""
    tokens = await accounts.change_password(
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        now=utc_now(),
    )
    return _apply_tokens(response, settings, tokens, use_cookie=_wants_cookie(transport))


@router.post(
    "/auth/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password-reset link",
    dependencies=[Depends(password_reset_rate_limit)],
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    accounts: AccountServiceDep,
    email_sender: EmailSenderDep,
    settings: SettingsDep,
) -> dict[str, str]:
    """Always 202, whether or not the address is registered.

    Reporting "no such account" here would turn this endpoint into a membership oracle —
    the same reason `/auth/login` gives one error for both unknown email and wrong password.
    """
    issued = await accounts.request_password_reset(email=str(payload.email), now=utc_now())
    if issued is not None:
        address, token = issued
        await email_sender.send_password_reset(
            email=address, token=token, ttl_minutes=settings.password_reset_ttl_minutes
        )
    return {"message": "If that address has an account, a reset link is on its way."}


@router.post(
    "/auth/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password from a reset link",
    dependencies=[Depends(password_reset_rate_limit)],
)
async def reset_password(payload: ResetPasswordRequest, accounts: AccountServiceDep) -> None:
    await accounts.reset_password(
        token=payload.token, new_password=payload.new_password, now=utc_now()
    )


@router.get("/me", response_model=MeResponse, summary="Current user")
async def read_me(user: CurrentUser) -> MeResponse:
    return MeResponse.model_validate(user)


@router.patch("/me", response_model=MeResponse, summary="Update profile")
async def update_me(
    payload: UpdateProfileRequest, user: CurrentUser, accounts: AccountServiceDep
) -> MeResponse:
    updated = await accounts.update_profile(
        user=user,
        display_name=payload.display_name,
        username=payload.username,
        avatar_url=payload.avatar_url,
        country_code=payload.country_code,
        study_category=payload.study_category,
        bio=payload.bio,
    )
    return MeResponse.model_validate(updated)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT, summary="Delete your account")
async def delete_me(
    response: Response,
    user: CurrentUser,
    accounts: AccountServiceDep,
    settings: SettingsDep,
) -> None:
    """Soft-delete now, purge later.

    Signs out every device and releases the email and username immediately; the record is
    removed for real by the worker once the grace period elapses, which is what leaves room
    to reverse an accidental deletion and keeps moderation history intact in the meantime.
    """
    await accounts.delete_account(user=user, now=utc_now())
    _clear_refresh_cookie(response, settings)


@router.patch("/me/settings", response_model=MeResponse, summary="Update settings")
async def update_settings(
    payload: UpdateSettingsRequest, user: CurrentUser, accounts: AccountServiceDep
) -> MeResponse:
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    updated = await accounts.update_settings(
        user=user, expected_version=payload.expected_version, **changes
    )
    return MeResponse.model_validate(updated)
