"""League seasons, divisions, cohorts, enrollments, scores, and missions.

Categories are rows, not code: adding "medical school" is an INSERT. Each season freezes
the scoring config it launched with so historical standings stay reproducible (ADR-0006).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JsonDocument, UtcDateTime, UuidType
from app.models.enums import EnrollmentPlacement, SeasonStatus

DIVISION_NAME_MAX_LENGTH = 40
CATEGORY_NAME_MAX_LENGTH = 80
# Cohort labels are composed from a division name and a category name, so the column must be
# wider than both put together. Exported so the composition can be tested against the column
# rather than against a number someone has to remember to update.
COHORT_LABEL_MAX_LENGTH = 160


class LeagueCategory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A competition pool (software engineering, language learning, …)."""

    __tablename__ = "league_categories"

    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(CATEGORY_NAME_MAX_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class LeagueSeason(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "league_seasons"

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=SeasonStatus.UPCOMING.value
    )
    # Frozen copy of the ScoringConfig used all season, including its version string.
    scoring_config: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    promotion_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    relegation_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    divisions: Mapped[list[LeagueDivision]] = relationship(
        back_populates="season", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("ends_on > starts_on", name="ck_season_dates_ordered"),
        CheckConstraint(
            "promotion_rate >= 0 AND promotion_rate <= 1", name="ck_season_promotion_rate"
        ),
        CheckConstraint(
            "relegation_rate >= 0 AND relegation_rate <= 1", name="ck_season_relegation_rate"
        ),
        CheckConstraint(
            "promotion_rate + relegation_rate <= 1", name="ck_season_rates_leave_middle"
        ),
    )


class LeagueDivision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Bronze (tier 0) through Master (tier 5) within one season."""

    __tablename__ = "league_divisions"

    season_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("league_seasons.id", ondelete="CASCADE"), nullable=False
    )
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(DIVISION_NAME_MAX_LENGTH), nullable=False)

    season: Mapped[LeagueSeason] = relationship(back_populates="divisions")
    cohorts: Mapped[list[LeagueCohort]] = relationship(
        back_populates="division", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("season_id", "tier", name="uq_division_season_tier"),
        CheckConstraint("tier >= 0", name="ck_division_tier_non_negative"),
    )


class LeagueCohort(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """20–30 users of one category competing head to head inside a division."""

    __tablename__ = "league_cohorts"

    division_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("league_divisions.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("league_categories.id", ondelete="RESTRICT"), nullable=False
    )
    # Derived as "{division.name} · {category.name} · Group {letter}", so the width has to
    # cover its inputs: 40 (division) + 80 (category) + 13 of separators and suffix = 133.
    # It was 40, which silently truncated nothing on SQLite and raised on PostgreSQL.
    label: Mapped[str] = mapped_column(String(COHORT_LABEL_MAX_LENGTH), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=25)

    division: Mapped[LeagueDivision] = relationship(back_populates="cohorts")

    __table_args__ = (
        CheckConstraint("capacity BETWEEN 20 AND 30", name="ck_cohort_capacity_range"),
        Index("ix_cohorts_division_category", "division_id", "category_id"),
    )


class LeagueEnrollment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "league_enrollments"

    season_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("league_seasons.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    cohort_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("league_cohorts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    placement: Mapped[str] = mapped_column(
        String(12), nullable=False, default=EnrollmentPlacement.PROVISIONAL.value
    )
    final_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(12), nullable=True)

    scores: Mapped[list[LeagueScore]] = relationship(
        back_populates="enrollment", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("season_id", "user_id", name="uq_enrollment_season_user"),)


class LeagueScore(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One weekly score (0–1000) per enrollment. Upserted by the scoring job."""

    __tablename__ = "league_scores"

    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("league_enrollments.id", ondelete="CASCADE"), nullable=False
    )
    week_index: Mapped[int] = mapped_column(Integer, nullable=False)
    points_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scoring_version: Mapped[str] = mapped_column(String(16), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    enrollment: Mapped[LeagueEnrollment] = relationship(back_populates="scores")
    breakdown: Mapped[LeagueScoreBreakdown] = relationship(
        back_populates="score", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("enrollment_id", "week_index", name="uq_score_enrollment_week"),
        CheckConstraint("points_total BETWEEN 0 AND 1000", name="ck_score_points_range"),
        CheckConstraint("week_index BETWEEN 0 AND 51", name="ck_score_week_index_range"),
    )


class LeagueScoreBreakdown(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Per-component points plus the raw inputs, so a user can audit their own score."""

    __tablename__ = "league_score_breakdowns"

    score_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("league_scores.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    goal_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consistency_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    focus_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    task_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    participation_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inputs: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False, default=dict)
    excluded_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exclusion_reasons: Mapped[list[str]] = mapped_column(JsonDocument, nullable=False, default=list)

    score: Mapped[LeagueScore] = relationship(back_populates="breakdown")


class LeagueMission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "league_missions"

    season_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("league_seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str] = mapped_column(String(48), nullable=False)
    target: Mapped[int] = mapped_column(Integer, nullable=False)
    reward_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    week_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("season_id", "slug", name="uq_mission_season_slug"),
        CheckConstraint("target > 0", name="ck_mission_target_positive"),
        CheckConstraint("reward_points >= 0", name="ck_mission_reward_non_negative"),
    )


class UserMissionProgress(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "user_mission_progress"

    mission_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("league_missions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("mission_id", "user_id", name="uq_mission_progress_user"),
        CheckConstraint("progress >= 0", name="ck_mission_progress_non_negative"),
    )
