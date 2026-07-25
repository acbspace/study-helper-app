"""Track push delivery on notifications.

`pushed_at` is the idempotency marker for the push-delivery worker: NULL means "not yet
attempted", a timestamp means "considered", so a notification is never pushed twice.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_notification_pushed_at"
down_revision: str | None = "0004_user_is_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notifications", "pushed_at")
