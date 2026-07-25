"""Outbound transactional email.

An interface plus a logging implementation, deliberately: wiring a real provider is a
deployment decision, and a password-reset flow that cannot be exercised without SMTP
credentials is a flow nobody tests. The logging sender makes the whole path runnable locally
and in CI, and swapping in SES/Postmark/Resend later means writing one class.

Reset links are never logged at INFO in a deployed environment — see `LoggingEmailSender`.
"""

from __future__ import annotations

from typing import Protocol

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmailSender(Protocol):
    async def send_password_reset(self, *, email: str, token: str, ttl_minutes: int) -> None:
        """Deliver a reset link. Must not raise for an ordinary delivery failure."""


class LoggingEmailSender:
    """Records that an email would have been sent.

    In local and test environments the token itself is logged, because that is the only way
    to complete the flow without a mail server. Anywhere else the token is withheld: a reset
    token in a log file is a standing account-takeover primitive for anyone with log access.
    """

    def __init__(self, settings: Settings) -> None:
        self._reveal_token = not settings.is_deployed

    async def send_password_reset(self, *, email: str, token: str, ttl_minutes: int) -> None:
        logger.info(
            "password_reset_email",
            email=email,
            ttl_minutes=ttl_minutes,
            reset_token=token if self._reveal_token else "[withheld]",
        )


def build_email_sender(settings: Settings) -> EmailSender:
    return LoggingEmailSender(settings)
