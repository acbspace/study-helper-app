"""Hard-delete accounts whose grace period has elapsed.

Deletion is two-phase. `DELETE /me` soft-deletes immediately: every session is revoked and
the email and username are released, so from the user's side the account is gone and the
address is reusable at once. This job is the second phase — it removes the row for real once
the grace period has passed, which is what turns "we stopped showing your data" into "your
data is not here any more".

The gap between the two exists so an accidental or coerced deletion can be reversed, and so
moderation history survives someone deleting their account to escape a report.

Every row that hangs off `users.id` cascades on delete (see migration 0001), so removing the
user removes their sessions, plans, memberships, and tokens with it. Expired reset tokens and
revoked refresh tokens for *live* accounts are swept here too: they are dead weight that only
grows, and a stale credential row is a credential row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from app.core.clock import ensure_utc, utc_now
from app.core.logging import get_logger
from app.models.user import PasswordResetToken, RefreshToken, User
from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

#: How long a soft-deleted account is recoverable before it is destroyed.
DEFAULT_GRACE_DAYS = 30

#: Revoked refresh tokens are kept briefly after revocation so that a reuse attempt still
#: finds the row and can trigger family revocation rather than looking merely unknown.
REVOKED_TOKEN_RETENTION_DAYS = 7


@dataclass(frozen=True, slots=True)
class PurgeResult:
    accounts_purged: int
    reset_tokens_removed: int
    refresh_tokens_removed: int


async def purge_deleted_accounts(
    db: AsyncSession, *, now: datetime | None = None, grace_days: int = DEFAULT_GRACE_DAYS
) -> PurgeResult:
    moment = ensure_utc(now or utc_now())
    cutoff = moment - timedelta(days=grace_days)

    expired = await db.execute(
        select(User).where(User.deleted_at.is_not(None), User.deleted_at < cutoff)
    )
    users = list(expired.scalars().all())
    for user in users:
        # ORM delete rather than a bulk statement: SQLite enforces the cascades through the
        # foreign keys the session already has configured, and this keeps the two engines
        # behaving identically.
        await db.delete(user)

    reset_tokens = cast(
        "CursorResult[Any]",
        await db.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at < moment)),
    )
    refresh_tokens = cast(
        "CursorResult[Any]",
        await db.execute(
            delete(RefreshToken).where(
                RefreshToken.revoked_at.is_not(None),
                RefreshToken.revoked_at < moment - timedelta(days=REVOKED_TOKEN_RETENTION_DAYS),
            )
        ),
    )

    await db.commit()
    result = PurgeResult(
        accounts_purged=len(users),
        reset_tokens_removed=reset_tokens.rowcount or 0,
        refresh_tokens_removed=refresh_tokens.rowcount or 0,
    )
    logger.info(
        "account_purger_finished",
        accounts_purged=result.accounts_purged,
        reset_tokens_removed=result.reset_tokens_removed,
        refresh_tokens_removed=result.refresh_tokens_removed,
    )
    return result


async def run(ctx: dict[str, Any]) -> dict[str, int]:
    """ARQ entry point."""
    factory = ctx["session_factory"]
    async with factory() as db:
        result = await purge_deleted_accounts(db)
    return {
        "accounts_purged": result.accounts_purged,
        "reset_tokens_removed": result.reset_tokens_removed,
        "refresh_tokens_removed": result.refresh_tokens_removed,
    }
