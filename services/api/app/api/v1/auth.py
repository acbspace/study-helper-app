"""Authentication and account routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.deps import AccountServiceDep, CurrentUser
from app.api.rate_limit import login_rate_limit
from app.core.clock import utc_now
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UpdateProfileRequest,
    UpdateSettingsRequest,
)

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
)
async def register(payload: RegisterRequest, accounts: AccountServiceDep) -> AuthResponse:
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
        tokens=TokenResponse.model_validate(tokens),
    )


@router.post(
    "/auth/login",
    response_model=AuthResponse,
    summary="Sign in",
    dependencies=[Depends(login_rate_limit)],
)
async def login(payload: LoginRequest, accounts: AccountServiceDep) -> AuthResponse:
    user, tokens = await accounts.login(
        email=str(payload.email), password=payload.password, now=utc_now()
    )
    return AuthResponse(
        user=MeResponse.model_validate(user),
        tokens=TokenResponse.model_validate(tokens),
    )


@router.post("/auth/refresh", response_model=TokenResponse, summary="Rotate tokens")
async def refresh(payload: RefreshRequest, accounts: AccountServiceDep) -> TokenResponse:
    tokens = await accounts.refresh(refresh_token=payload.refresh_token, now=utc_now())
    return TokenResponse.model_validate(tokens)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a session")
async def logout(payload: RefreshRequest, accounts: AccountServiceDep) -> None:
    await accounts.logout(refresh_token=payload.refresh_token, now=utc_now())


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


@router.patch("/me/settings", response_model=MeResponse, summary="Update settings")
async def update_settings(
    payload: UpdateSettingsRequest, user: CurrentUser, accounts: AccountServiceDep
) -> MeResponse:
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    updated = await accounts.update_settings(
        user=user, expected_version=payload.expected_version, **changes
    )
    return MeResponse.model_validate(updated)
