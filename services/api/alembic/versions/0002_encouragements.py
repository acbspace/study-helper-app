"""Persist encouragement reactions.

Reactions are delivered live over the realtime socket, but the league scores "positive group
participation" from them — and a season's standings must stay recomputable from stored inputs
(ADR-0006). So the reaction itself is durable even though its delivery is best-effort.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_encouragements"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "encouragements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("from_user_id", sa.Uuid(), nullable=False),
        sa.Column("to_user_id", sa.Uuid(), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("from_user_id <> to_user_id", name="ck_encouragement_not_self"),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_encouragements_to_user_id", "encouragements", ["to_user_id"])
    op.create_index(
        "ix_encouragements_from_created", "encouragements", ["from_user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_encouragements_from_created", table_name="encouragements")
    op.drop_index("ix_encouragements_to_user_id", table_name="encouragements")
    op.drop_table("encouragements")
