"""Widen league_cohorts.label to fit the names it is composed from.

The label is built as "{division.name} · {category.name} · Group {letter}", but the column
was varchar(40) while a division name alone may be 40 and a category name 80. Ten of the
seeded division x category combinations already exceeded it — "Platinum · Professional
Certifications · Group A" is 48 characters.

SQLite ignores VARCHAR limits, so the whole test suite passed locally while every write of
an affected label raised StringDataRightTruncationError on PostgreSQL. This widens the
column to 160, which is above the structural maximum of 133, so the composition cannot
overflow it whatever names a season is configured with.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_widen_cohort_label"
down_revision: str | None = "0005_notification_pushed_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "league_cohorts",
        "label",
        existing_type=sa.String(length=40),
        type_=sa.String(length=160),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Narrowing again would truncate labels that the widened column legitimately holds, so
    # the rows are trimmed first rather than letting the ALTER fail on real data.
    op.execute("UPDATE league_cohorts SET label = substr(label, 1, 40)")
    op.alter_column(
        "league_cohorts",
        "label",
        existing_type=sa.String(length=160),
        type_=sa.String(length=40),
        existing_nullable=False,
    )
