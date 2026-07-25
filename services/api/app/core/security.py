"""Password hashing, JWT issuance/verification, and opaque token helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode

_password_hash = PasswordHash.recommended()

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_WS_TICKET = "ws"


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hash.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


def create_access_token(
    settings: Settings, user_id: uuid.UUID, *, now: datetime | None = None
) -> tuple[str, int]:
    """Return an access token and its lifetime in seconds."""
    issued_at = now or datetime.now(UTC)
    ttl = timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
        "typ": TOKEN_TYPE_ACCESS,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(ttl.total_seconds())


def decode_access_token(settings: Settings, token: str) -> uuid.UUID:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except jwt.ExpiredSignatureError as exc:
        raise AppError(
            ErrorCode.TOKEN_EXPIRED, "Access token has expired.", status_code=401
        ) from exc
    except jwt.PyJWTError as exc:
        raise AppError(
            ErrorCode.NOT_AUTHENTICATED, "Invalid authentication token.", status_code=401
        ) from exc

    if payload.get("typ") != TOKEN_TYPE_ACCESS:
        raise AppError(
            ErrorCode.NOT_AUTHENTICATED, "Invalid authentication token.", status_code=401
        )
    try:
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise AppError(
            ErrorCode.NOT_AUTHENTICATED, "Invalid authentication token.", status_code=401
        ) from exc


def mint_ws_ticket(
    settings: Settings, user_id: uuid.UUID, *, now: datetime | None = None
) -> tuple[str, int]:
    """A short-lived, single-purpose token for opening a realtime socket.

    Separate `typ` from access tokens so a ticket can never be replayed as an API bearer and
    vice versa, and a tight TTL so the value in the URL is useless within a minute.
    """
    issued_at = now or datetime.now(UTC)
    ttl = timedelta(seconds=settings.ws_ticket_ttl_seconds)
    payload = {
        "sub": str(user_id),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
        "typ": TOKEN_TYPE_WS_TICKET,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(ttl.total_seconds())


def verify_ws_ticket(settings: Settings, token: str) -> uuid.UUID:
    """Validate a realtime ticket and return the user it authenticates."""
    invalid = AppError(ErrorCode.NOT_AUTHENTICATED, "Invalid realtime ticket.", status_code=401)
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except jwt.PyJWTError as exc:
        raise invalid from exc

    if payload.get("typ") != TOKEN_TYPE_WS_TICKET:
        raise invalid
    try:
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise invalid from exc


def generate_refresh_token() -> str:
    """Opaque, high-entropy refresh token. Only its hash is ever stored."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_device_identifier(settings: Settings, raw_device_id: str) -> str:
    """Salted hash of a client installation id — raw vendor ids are never persisted."""
    return hmac.new(
        settings.device_hash_salt.encode("utf-8"),
        raw_device_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
