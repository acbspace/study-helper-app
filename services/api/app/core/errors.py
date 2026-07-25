"""Stable, machine-readable error codes and the single error envelope.

Clients branch on `code`, never on message text. See docs/api/API_CONVENTIONS.md.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    NOT_AUTHENTICATED = "not_authenticated"
    TOKEN_EXPIRED = "token_expired"
    INVALID_CREDENTIALS = "invalid_credentials"
    NOT_PERMITTED = "not_permitted"
    RATE_LIMITED = "rate_limited"

    EMAIL_ALREADY_REGISTERED = "email_already_registered"
    USERNAME_TAKEN = "username_taken"
    INVALID_RESET_TOKEN = "invalid_reset_token"
    PASSWORD_TOO_WEAK = "password_too_weak"

    SUBJECT_NOT_FOUND = "subject_not_found"
    SUBJECT_NAME_TAKEN = "subject_name_taken"

    SESSION_NOT_FOUND = "session_not_found"
    ACTIVE_SESSION_EXISTS = "active_session_exists"
    INVALID_TRANSITION = "invalid_transition"
    TIMELINE_INVALID = "timeline_invalid"

    PLAN_NOT_FOUND = "plan_not_found"
    TASK_NOT_FOUND = "task_not_found"
    GOAL_NOT_FOUND = "goal_not_found"

    USER_NOT_FOUND = "user_not_found"
    FRIENDSHIP_NOT_FOUND = "friendship_not_found"
    FRIEND_REQUEST_EXISTS = "friend_request_exists"
    ALREADY_FRIENDS = "already_friends"
    CANNOT_FRIEND_SELF = "cannot_friend_self"
    USER_BLOCKED = "user_blocked"

    GROUP_NOT_FOUND = "group_not_found"
    NOT_GROUP_MEMBER = "not_group_member"
    ALREADY_GROUP_MEMBER = "already_group_member"
    GROUP_FULL = "group_full"
    INVALID_INVITE_CODE = "invalid_invite_code"
    INVITATION_NOT_FOUND = "invitation_not_found"
    INVITATION_EXISTS = "invitation_exists"
    OWNER_CANNOT_LEAVE = "owner_cannot_leave"

    NO_ACTIVE_SEASON = "no_active_season"
    NOT_ENROLLED = "not_enrolled"
    SCORE_NOT_FOUND = "score_not_found"

    POST_NOT_FOUND = "post_not_found"
    COMMENT_NOT_FOUND = "comment_not_found"

    REPORT_EXISTS = "report_exists"
    REPORT_NOT_FOUND = "report_not_found"
    CANNOT_REPORT_SELF = "cannot_report_self"
    NOTIFICATION_NOT_FOUND = "notification_not_found"
    DEVICE_REQUIRED = "device_required"

    VERSION_CONFLICT = "version_conflict"
    INTERNAL_ERROR = "internal_error"


class AppError(Exception):
    """Domain-level failure carrying an HTTP status and a stable code.

    Raised by domain services; translated to the error envelope by one exception handler.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code.value, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return {"error": payload}


class NotFoundError(AppError):
    def __init__(self, code: ErrorCode, message: str, **details: Any) -> None:
        super().__init__(code, message, status_code=404, details=details or None)


class ConflictError(AppError):
    def __init__(self, code: ErrorCode, message: str, **details: Any) -> None:
        super().__init__(code, message, status_code=409, details=details or None)


class ForbiddenError(AppError):
    """The caller is authenticated but not allowed to perform this action.

    Use only where the resource's existence is not itself private; otherwise prefer
    `NotFoundError` so ownership cannot be probed.
    """

    def __init__(self, message: str = "You do not have access to this resource.") -> None:
        super().__init__(ErrorCode.NOT_PERMITTED, message, status_code=403)


class UnprocessableError(AppError):
    def __init__(self, code: ErrorCode, message: str, **details: Any) -> None:
        super().__init__(code, message, status_code=422, details=details or None)
