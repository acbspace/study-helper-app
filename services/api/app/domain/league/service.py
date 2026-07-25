"""The seasonal league: placement, weekly scoring runs, standings, and season close-out.

Design commitments this module keeps (PRD §6, ADR-0006):

* **Server-side and deterministic.** Points are only ever computed here from stored facts and
  the season's frozen config, never sent by a client.
* **Reproducible.** Every weekly score is stored with the inputs and the scoring version that
  produced it, so a past season can be re-derived and explained.
* **Cohorts are like-for-like.** Users compete inside their own league category and division,
  in groups small enough (20–30) that the ladder feels reachable.
* **Re-running is safe.** The weekly run upserts by `(enrollment, week)`, so a retried or
  re-scheduled job converges rather than duplicating.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.clock import utc_now
from app.core.errors import ErrorCode, NotFoundError
from app.domain.league.facts import LeagueFactsService
from app.domain.league.missions import MissionInputs
from app.domain.league.missions import evaluate as evaluate_missions
from app.domain.scoring.config import ScoringConfig
from app.domain.scoring.models import WeeklyScoreBreakdown, WeeklyScoreInput
from app.domain.scoring.service import score_week
from app.domain.social.service import PublicUserView, load_public_users
from app.models.enums import EnrollmentPlacement, SeasonOutcome, SeasonStatus
from app.models.league import (
    LeagueCategory,
    LeagueCohort,
    LeagueDivision,
    LeagueEnrollment,
    LeagueMission,
    LeagueScore,
    LeagueScoreBreakdown,
    LeagueSeason,
    UserMissionProgress,
)
from app.models.user import User

DEFAULT_CATEGORY_SLUG = "general_productivity"


@dataclass(frozen=True, slots=True)
class WeekPoints:
    week_index: int
    points: int


@dataclass(frozen=True, slots=True)
class LeagueStanding:
    season_id: uuid.UUID
    season_name: str
    starts_on: date
    ends_on: date
    status: str
    division_tier: int
    division_name: str
    cohort_id: uuid.UUID
    cohort_label: str
    category_name: str
    placement: str
    rank: int
    cohort_size: int
    total_points: int
    weeks: list[WeekPoints]


@dataclass(frozen=True, slots=True)
class LeaderboardEntry:
    rank: int
    user: PublicUserView
    total_points: int
    placement: str
    is_me: bool


@dataclass(frozen=True, slots=True)
class ComponentView:
    name: str
    points: int
    max_points: int
    detail: dict[str, object]


@dataclass(frozen=True, slots=True)
class BreakdownView:
    week_index: int
    week_start: date
    total_points: int
    scoring_version: str
    components: list[ComponentView]
    excluded_seconds: int
    exclusion_reasons: list[str]


@dataclass(frozen=True, slots=True)
class MissionProgressView:
    id: uuid.UUID
    slug: str
    title: str
    description: str
    target: int
    reward_points: int
    progress: int
    completed: bool


@dataclass(frozen=True, slots=True)
class SeasonHistoryEntry:
    season_id: uuid.UUID
    season_name: str
    division_name: str
    total_points: int
    final_rank: int | None
    outcome: str | None


class LeagueService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._facts = LeagueFactsService(db)

    # ------------------------------------------------------------------ seasons

    async def active_season(self) -> LeagueSeason | None:
        result = await self._db.execute(
            select(LeagueSeason).where(LeagueSeason.status == SeasonStatus.ACTIVE.value)
        )
        return result.scalars().first()

    async def _require_active_season(self) -> LeagueSeason:
        season = await self.active_season()
        if season is None:
            raise NotFoundError(ErrorCode.NO_ACTIVE_SEASON, "No league season is running.")
        return season

    def week_index_for(self, season: LeagueSeason, day: date) -> int:
        """Which season week a local day falls in, clamped to the season's length."""
        weeks = max(0, (day - season.starts_on).days // 7)
        last_week = max(0, (season.ends_on - season.starts_on).days // 7)
        return min(weeks, last_week)

    # ------------------------------------------------------------------ enrollment

    async def ensure_enrollment(self, user: User) -> LeagueEnrollment:
        """Enrol the user in the running season, placing them in a like-for-like cohort."""
        season = await self._require_active_season()
        existing = await self._enrollment_for(season.id, user.id)
        if existing is not None:
            return existing

        category = await self._category_for(user)
        division = await self._entry_division(season.id)
        cohort = await self._cohort_with_room(division, category)

        enrollment = LeagueEnrollment(
            season_id=season.id,
            user_id=user.id,
            cohort_id=cohort.id,
            placement=EnrollmentPlacement.PROVISIONAL.value,
        )
        self._db.add(enrollment)
        await self._db.commit()
        await self._db.refresh(enrollment)
        return enrollment

    async def _enrollment_for(
        self, season_id: uuid.UUID, user_id: uuid.UUID
    ) -> LeagueEnrollment | None:
        result = await self._db.execute(
            select(LeagueEnrollment).where(
                LeagueEnrollment.season_id == season_id,
                LeagueEnrollment.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _category_for(self, user: User) -> LeagueCategory:
        """Match the user's study category, falling back so nobody is left unplaceable."""
        for slug in (user.profile.study_category, DEFAULT_CATEGORY_SLUG):
            result = await self._db.execute(
                select(LeagueCategory).where(
                    LeagueCategory.slug == slug, LeagueCategory.is_active.is_(True)
                )
            )
            category = result.scalars().first()
            if category is not None:
                return category

        result = await self._db.execute(
            select(LeagueCategory)
            .where(LeagueCategory.is_active.is_(True))
            .order_by(LeagueCategory.sort_order)
        )
        category = result.scalars().first()
        if category is None:
            raise NotFoundError(ErrorCode.NO_ACTIVE_SEASON, "No league categories configured.")
        return category

    async def _entry_division(self, season_id: uuid.UUID) -> LeagueDivision:
        """New users start at the bottom tier and climb."""
        result = await self._db.execute(
            select(LeagueDivision)
            .where(LeagueDivision.season_id == season_id)
            .order_by(LeagueDivision.tier)
        )
        division = result.scalars().first()
        if division is None:
            raise NotFoundError(ErrorCode.NO_ACTIVE_SEASON, "The season has no divisions.")
        return division

    async def _cohort_with_room(
        self, division: LeagueDivision, category: LeagueCategory
    ) -> LeagueCohort:
        """First cohort under capacity, or a fresh one — cohorts stay small on purpose."""
        result = await self._db.execute(
            select(LeagueCohort)
            .where(
                LeagueCohort.division_id == division.id,
                LeagueCohort.category_id == category.id,
            )
            .order_by(LeagueCohort.created_at)
        )
        cohorts = list(result.scalars().all())
        for cohort in cohorts:
            if await self._cohort_size(cohort.id) < cohort.capacity:
                return cohort

        cohort = LeagueCohort(
            division_id=division.id,
            category_id=category.id,
            label=f"{division.name} · {category.name} · Group {chr(ord('A') + len(cohorts))}",
            capacity=25,
        )
        self._db.add(cohort)
        await self._db.flush()
        return cohort

    async def _cohort_size(self, cohort_id: uuid.UUID) -> int:
        result = await self._db.execute(
            select(func.count())
            .select_from(LeagueEnrollment)
            .where(LeagueEnrollment.cohort_id == cohort_id)
        )
        return int(result.scalar_one())

    # ------------------------------------------------------------------ scoring

    async def run_weekly_scoring(
        self, *, season: LeagueSeason, week_index: int, user_id: uuid.UUID | None = None
    ) -> int:
        """Score every enrollment for one week. Idempotent: re-running overwrites in place."""
        config = ScoringConfig.from_dict(season.scoring_config)
        week_start = season.starts_on + timedelta(weeks=week_index)

        query = select(LeagueEnrollment).where(LeagueEnrollment.season_id == season.id)
        if user_id is not None:
            query = query.where(LeagueEnrollment.user_id == user_id)
        enrollments = list((await self._db.execute(query)).scalars().all())

        scored = 0
        for enrollment in enrollments:
            user = await self._load_user(enrollment.user_id)
            if user is None:
                continue
            facts = await self._facts.weekly_input(user=user, week_start=week_start)
            breakdown = score_week(facts, config)
            await self._persist_score(enrollment, week_index, facts, breakdown)
            await self._persist_missions(season, user, facts, config, week_start, week_index)
            scored += 1

        await self._db.commit()
        return scored

    async def _persist_score(
        self,
        enrollment: LeagueEnrollment,
        week_index: int,
        facts: WeeklyScoreInput,
        breakdown: WeeklyScoreBreakdown,
    ) -> None:
        result = await self._db.execute(
            select(LeagueScore)
            .options(selectinload(LeagueScore.breakdown))
            .where(
                LeagueScore.enrollment_id == enrollment.id,
                LeagueScore.week_index == week_index,
            )
        )
        score = result.scalar_one_or_none()
        # Read the relationship only on a row that was loaded with it: touching it on a
        # pending object would fire a lazy load, which is not allowed under async IO.
        detail: LeagueScoreBreakdown | None
        if score is None:
            score = LeagueScore(enrollment_id=enrollment.id, week_index=week_index)
            self._db.add(score)
            detail = None
        else:
            detail = score.breakdown

        score.points_total = breakdown.total_points
        score.scoring_version = breakdown.scoring_version
        score.computed_at = utc_now()
        await self._db.flush()

        if detail is None:
            detail = LeagueScoreBreakdown(score_id=score.id)
            self._db.add(detail)

        detail.goal_points = breakdown.goal.points
        detail.consistency_points = breakdown.consistency.points
        detail.focus_points = breakdown.focus.points
        detail.task_points = breakdown.tasks.points
        detail.participation_points = breakdown.participation.points
        detail.excluded_seconds = breakdown.excluded_seconds
        detail.exclusion_reasons = list(breakdown.exclusion_reasons)
        detail.inputs = _serialize_inputs(facts, breakdown)

    async def _persist_missions(
        self,
        season: LeagueSeason,
        user: User,
        facts: WeeklyScoreInput,
        config: ScoringConfig,
        week_start: date,
        week_index: int,
    ) -> None:
        """Recompute this week's mission progress. Overwrites, so re-runs converge."""
        missions = list(
            (
                await self._db.execute(
                    select(LeagueMission).where(LeagueMission.season_id == season.id)
                )
            )
            .scalars()
            .all()
        )
        if not missions:
            return

        extra = MissionInputs(
            early_sessions_completed=await self._facts.early_sessions_completed(
                user=user, week_start=week_start
            )
        )
        progress_by_metric = evaluate_missions(facts, config, extra)

        for mission in missions:
            # A mission pinned to another week is not in play right now.
            if mission.week_index is not None and mission.week_index != week_index:
                continue
            progress = progress_by_metric.get(mission.metric)
            if progress is None:  # an unknown metric has no evaluator yet
                continue

            record = (
                await self._db.execute(
                    select(UserMissionProgress).where(
                        UserMissionProgress.mission_id == mission.id,
                        UserMissionProgress.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            if record is None:
                record = UserMissionProgress(mission_id=mission.id, user_id=user.id)
                self._db.add(record)

            record.progress = progress
            record.completed_at = utc_now() if progress >= mission.target else None

    async def missions(self, user: User) -> list[MissionProgressView]:
        season = await self._require_active_season()
        rows = list(
            (
                await self._db.execute(
                    select(LeagueMission)
                    .where(LeagueMission.season_id == season.id)
                    .order_by(LeagueMission.reward_points.desc(), LeagueMission.slug)
                )
            )
            .scalars()
            .all()
        )
        progress = {
            row.mission_id: row
            for row in (
                await self._db.execute(
                    select(UserMissionProgress).where(UserMissionProgress.user_id == user.id)
                )
            )
            .scalars()
            .all()
        }
        return [
            MissionProgressView(
                id=mission.id,
                slug=mission.slug,
                title=mission.title,
                description=mission.description,
                target=mission.target,
                reward_points=mission.reward_points,
                progress=progress[mission.id].progress if mission.id in progress else 0,
                completed=(
                    mission.id in progress and progress[mission.id].completed_at is not None
                ),
            )
            for mission in rows
        ]

    async def _load_user(self, user_id: uuid.UUID) -> User | None:
        result = await self._db.execute(
            select(User)
            .options(selectinload(User.profile), selectinload(User.settings))
            .where(User.id == user_id, User.deleted_at.is_(None), User.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------ standings

    async def standing(self, user: User) -> LeagueStanding:
        season = await self._require_active_season()
        enrollment = await self._enrollment_for(season.id, user.id)
        if enrollment is None:
            raise NotFoundError(ErrorCode.NOT_ENROLLED, "You are not in this season yet.")

        cohort, division, category = await self._cohort_context(enrollment)
        totals = await self._cohort_totals(enrollment.cohort_id)
        ordered = _rank(totals)
        rank = next((r for r, (uid, _) in ordered if uid == user.id), len(totals))

        weeks = await self._weeks_for(enrollment.id)
        return LeagueStanding(
            season_id=season.id,
            season_name=season.name,
            starts_on=season.starts_on,
            ends_on=season.ends_on,
            status=season.status,
            division_tier=division.tier,
            division_name=division.name,
            cohort_id=cohort.id,
            cohort_label=cohort.label,
            category_name=category.name,
            placement=enrollment.placement,
            rank=rank,
            cohort_size=len(totals),
            total_points=sum(week.points for week in weeks),
            weeks=weeks,
        )

    async def leaderboard(self, user: User) -> list[LeaderboardEntry]:
        season = await self._require_active_season()
        enrollment = await self._enrollment_for(season.id, user.id)
        if enrollment is None:
            raise NotFoundError(ErrorCode.NOT_ENROLLED, "You are not in this season yet.")

        totals = await self._cohort_totals(enrollment.cohort_id)
        placements = await self._placements(enrollment.cohort_id)
        profiles = await load_public_users(self._db, set(totals))

        entries: list[LeaderboardEntry] = []
        for rank, (user_id, points) in _rank(totals):
            profile = profiles.get(user_id)
            if profile is None:
                continue
            entries.append(
                LeaderboardEntry(
                    rank=rank,
                    user=profile,
                    total_points=points,
                    placement=placements.get(user_id, EnrollmentPlacement.PROVISIONAL.value),
                    is_me=user_id == user.id,
                )
            )
        return entries

    async def breakdown(self, user: User, week_index: int) -> BreakdownView:
        season = await self._require_active_season()
        enrollment = await self._enrollment_for(season.id, user.id)
        if enrollment is None:
            raise NotFoundError(ErrorCode.NOT_ENROLLED, "You are not in this season yet.")

        result = await self._db.execute(
            select(LeagueScore)
            .options(selectinload(LeagueScore.breakdown))
            .where(
                LeagueScore.enrollment_id == enrollment.id,
                LeagueScore.week_index == week_index,
            )
        )
        score = result.scalar_one_or_none()
        if score is None or score.breakdown is None:
            raise NotFoundError(ErrorCode.SCORE_NOT_FOUND, "That week has not been scored yet.")

        stored = score.breakdown
        components = stored.inputs.get("components", []) if stored.inputs else []
        return BreakdownView(
            week_index=score.week_index,
            week_start=season.starts_on + timedelta(weeks=score.week_index),
            total_points=score.points_total,
            scoring_version=score.scoring_version,
            components=[
                ComponentView(
                    name=str(item.get("name", "")),
                    points=int(item.get("points", 0)),
                    max_points=int(item.get("max_points", 0)),
                    detail=dict(item.get("detail", {})),
                )
                for item in components
                if isinstance(item, dict)
            ],
            excluded_seconds=stored.excluded_seconds,
            exclusion_reasons=list(stored.exclusion_reasons or []),
        )

    async def history(self, user: User) -> list[SeasonHistoryEntry]:
        result = await self._db.execute(
            select(LeagueEnrollment, LeagueSeason)
            .join(LeagueSeason, LeagueSeason.id == LeagueEnrollment.season_id)
            .where(LeagueEnrollment.user_id == user.id)
            .order_by(LeagueSeason.starts_on.desc())
        )
        entries: list[SeasonHistoryEntry] = []
        for enrollment, season in result.all():
            weeks = await self._weeks_for(enrollment.id)
            division_name = "—"
            if enrollment.cohort_id is not None:
                _, division, _ = await self._cohort_context(enrollment)
                division_name = division.name
            entries.append(
                SeasonHistoryEntry(
                    season_id=season.id,
                    season_name=season.name,
                    division_name=division_name,
                    total_points=sum(week.points for week in weeks),
                    final_rank=enrollment.final_rank,
                    outcome=enrollment.outcome,
                )
            )
        return entries

    # ------------------------------------------------------------------ close-out

    async def close_season(self, season: LeagueSeason) -> int:
        """Rank every cohort, assign promotion/relegation, and freeze the season.

        Inactive users (no points at all) are marked unranked rather than relegated: not
        playing is not the same as playing badly.
        """
        cohort_ids = list(
            (
                await self._db.execute(
                    select(LeagueEnrollment.cohort_id)
                    .where(LeagueEnrollment.season_id == season.id)
                    .distinct()
                )
            ).scalars()
        )

        closed = 0
        for cohort_id in cohort_ids:
            if cohort_id is None:
                continue
            totals = await self._cohort_totals(cohort_id)
            ordered = _rank(totals)
            size = len(ordered)
            promote = round(size * season.promotion_rate)
            relegate = round(size * season.relegation_rate)

            for rank, (user_id, points) in ordered:
                enrollment = await self._enrollment_for(season.id, user_id)
                if enrollment is None:
                    continue
                enrollment.final_rank = rank
                if points <= 0:
                    enrollment.outcome = SeasonOutcome.UNRANKED.value
                    enrollment.placement = EnrollmentPlacement.UNRANKED.value
                elif rank <= promote:
                    enrollment.outcome = SeasonOutcome.PROMOTED.value
                    enrollment.placement = EnrollmentPlacement.RANKED.value
                elif rank > size - relegate:
                    enrollment.outcome = SeasonOutcome.RELEGATED.value
                    enrollment.placement = EnrollmentPlacement.RANKED.value
                else:
                    enrollment.outcome = SeasonOutcome.RETAINED.value
                    enrollment.placement = EnrollmentPlacement.RANKED.value
                closed += 1

        season.status = SeasonStatus.CLOSED.value
        season.closed_at = utc_now()
        await self._db.commit()
        return closed

    # ------------------------------------------------------------------ helpers

    async def _cohort_context(
        self, enrollment: LeagueEnrollment
    ) -> tuple[LeagueCohort, LeagueDivision, LeagueCategory]:
        result = await self._db.execute(
            select(LeagueCohort, LeagueDivision, LeagueCategory)
            .join(LeagueDivision, LeagueDivision.id == LeagueCohort.division_id)
            .join(LeagueCategory, LeagueCategory.id == LeagueCohort.category_id)
            .where(LeagueCohort.id == enrollment.cohort_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError(ErrorCode.NOT_ENROLLED, "Your cohort is no longer available.")
        cohort, division, category = row
        return cohort, division, category

    async def _cohort_totals(self, cohort_id: uuid.UUID | None) -> dict[uuid.UUID, int]:
        """Total points per user in a cohort — everyone, including those on zero."""
        if cohort_id is None:
            return {}
        enrollments = list(
            (
                await self._db.execute(
                    select(LeagueEnrollment).where(LeagueEnrollment.cohort_id == cohort_id)
                )
            )
            .scalars()
            .all()
        )
        if not enrollments:
            return {}

        by_enrollment = {enrollment.id: enrollment.user_id for enrollment in enrollments}
        sums = await self._db.execute(
            select(LeagueScore.enrollment_id, func.coalesce(func.sum(LeagueScore.points_total), 0))
            .where(LeagueScore.enrollment_id.in_(list(by_enrollment)))
            .group_by(LeagueScore.enrollment_id)
        )
        totals: dict[uuid.UUID, int] = dict.fromkeys(by_enrollment.values(), 0)
        for enrollment_id, points in sums.all():
            totals[by_enrollment[enrollment_id]] = int(points)
        return totals

    async def _placements(self, cohort_id: uuid.UUID | None) -> dict[uuid.UUID, str]:
        if cohort_id is None:
            return {}
        result = await self._db.execute(
            select(LeagueEnrollment.user_id, LeagueEnrollment.placement).where(
                LeagueEnrollment.cohort_id == cohort_id
            )
        )
        return {row.user_id: row.placement for row in result.all()}

    async def _weeks_for(self, enrollment_id: uuid.UUID) -> list[WeekPoints]:
        result = await self._db.execute(
            select(LeagueScore)
            .where(LeagueScore.enrollment_id == enrollment_id)
            .order_by(LeagueScore.week_index)
        )
        return [
            WeekPoints(week_index=score.week_index, points=score.points_total)
            for score in result.scalars().all()
        ]


def _rank(totals: dict[uuid.UUID, int]) -> list[tuple[int, tuple[uuid.UUID, int]]]:
    """Rank users by points, breaking ties by id so ordering is stable and reproducible."""
    ordered = sorted(totals.items(), key=lambda item: (-item[1], str(item[0])))
    return [(index + 1, entry) for index, entry in enumerate(ordered)]


def _serialize_inputs(
    facts: WeeklyScoreInput, breakdown: WeeklyScoreBreakdown
) -> dict[str, object]:
    """Everything needed to explain — and re-derive — this score."""
    payload = breakdown.to_dict()
    payload["inputs"] = {
        "days": [
            {
                "day": day.day.isoformat(),
                "is_scheduled": day.is_scheduled,
                "verified_seconds": day.verified_seconds,
                "manual_seconds": day.manual_seconds,
                "excluded_seconds": day.excluded_seconds,
                "goal_minutes": day.goal_minutes,
            }
            for day in facts.days
        ],
        "focus_sessions_completed": facts.focus_sessions_completed,
        "tasks_planned": facts.tasks_planned,
        "tasks_completed": facts.tasks_completed,
        "participation_events": facts.participation_events,
    }
    return payload
