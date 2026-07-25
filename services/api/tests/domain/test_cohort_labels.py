"""Cohort labels must fit the column that stores them.

This is the regression guard for migration 0006. The label is composed from a division name
and a category name, and the column was narrower than its own inputs — but SQLite ignores
VARCHAR limits, so the entire suite passed locally while every affected write raised
StringDataRightTruncationError on PostgreSQL.

These assertions are engine-independent on purpose: they compare the composition against the
declared column width rather than relying on a database to enforce it, so the bug cannot come
back through whichever engine the suite happens to run on.
"""

from __future__ import annotations

import string

from app.domain.league.service import build_cohort_label
from app.models.league import (
    CATEGORY_NAME_MAX_LENGTH,
    COHORT_LABEL_MAX_LENGTH,
    DIVISION_NAME_MAX_LENGTH,
    LeagueCohort,
)
from app.seed import CATEGORIES, DIVISIONS


def test_label_column_is_wide_enough_for_any_valid_composition() -> None:
    """The widest label the code can build must fit, whatever a season is configured with."""
    widest = build_cohort_label(
        division_name="D" * DIVISION_NAME_MAX_LENGTH,
        category_name="C" * CATEGORY_NAME_MAX_LENGTH,
        group_index=len(string.ascii_uppercase) - 1,
    )
    assert len(widest) <= COHORT_LABEL_MAX_LENGTH


def test_declared_column_width_matches_the_model() -> None:
    """Guards against the constant and the mapped column drifting apart."""
    column = LeagueCohort.__table__.c.label
    assert column.type.length == COHORT_LABEL_MAX_LENGTH


def test_every_seeded_division_and_category_pair_fits() -> None:
    """The exact data the seed writes — "Platinum · Professional Certifications" overflowed."""
    for _tier, division_name in DIVISIONS:
        for _slug, category_name in CATEGORIES:
            label = build_cohort_label(
                division_name=division_name, category_name=category_name, group_index=0
            )
            assert len(label) <= COHORT_LABEL_MAX_LENGTH, label


def test_group_letter_advances_with_the_index() -> None:
    common = {"division_name": "Gold", "category_name": "Entrance Exams"}
    assert build_cohort_label(**common, group_index=0) == "Gold · Entrance Exams · Group A"
    assert build_cohort_label(**common, group_index=1) == "Gold · Entrance Exams · Group B"
