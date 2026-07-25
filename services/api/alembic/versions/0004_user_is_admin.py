"""Add the moderator flag to users.

Moderation is gated on `users.is_admin`, set out-of-band (seed, ops) — never granted through
a public endpoint. Defaults false so existing accounts are unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_user_is_admin"
down_revision: str | None = "0003_community"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the server default (`false`) rather than dropping it in a follow-up batch: on
    # SQLite that follow-up recreates the whole table and would skip the expression-based
    # unique indexes on email/username. A harmless DB-level default alongside the model's
    # Python default is the safer trade.
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
