"""Development seed data.

Creates a demo account with subjects, a week of realistic study history, tasks, and an
active league season. Idempotent: running it twice does not duplicate anything.

    python -m app.seed
"""

from __future__ import annotations

import asyncio
import random
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.db.session import create_engine, create_session_factory
from app.domain.league.service import build_cohort_label
from app.domain.scoring import SCORING_CONFIG_V1
from app.models.enums import (
    AuthProvider,
    FocusMode,
    IntegrityStatus,
    MissionMetric,
    SeasonStatus,
    SessionEventType,
    SessionSource,
    SessionStatus,
    TaskPriority,
    TaskStatus,
)
from app.models.league import (
    LeagueCategory,
    LeagueCohort,
    LeagueDivision,
    LeagueMission,
    LeagueSeason,
)
from app.models.planner import DailyPlan, Task
from app.models.study import StudySession, StudySessionEvent, Subject
from app.models.user import User, UserProfile, UserSettings

logger = get_logger(__name__)

# Must be a deliverable-looking address: the login endpoint validates emails, so a
# reserved TLD such as .test would make the seeded account impossible to sign in with.
DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "studyleague123"

CATEGORIES: list[tuple[str, str]] = [
    ("software_engineering", "Software Engineering"),
    ("university", "University Coursework"),
    ("entrance_exams", "Entrance Exams"),
    ("standardized_tests", "Standardized Tests"),
    ("language_learning", "Language Learning"),
    ("professional_certifications", "Professional Certifications"),
    ("general_productivity", "General Productivity"),
]

DIVISIONS: list[tuple[int, str]] = [
    (0, "Bronze"),
    (1, "Silver"),
    (2, "Gold"),
    (3, "Platinum"),
    (4, "Diamond"),
    (5, "Master"),
]

SUBJECTS: list[tuple[str, str]] = [
    ("Algorithms", "#4F6BED"),
    ("System Design", "#E86A5B"),
    ("Databases", "#37B27A"),
    ("Korean", "#B565D8"),
]

MISSIONS: list[tuple[str, str, str, MissionMetric, int, int]] = [
    (
        "three-planned-sessions",
        "Follow the plan",
        "Complete three sessions you planned in advance.",
        MissionMetric.PLANNED_SESSIONS_COMPLETED,
        3,
        30,
    ),
    (
        "goal-four-times",
        "Four on target",
        "Reach your daily goal on four days this week.",
        MissionMetric.DAILY_GOAL_REACHED,
        4,
        40,
    ),
    (
        "five-scheduled-days",
        "Steady week",
        "Study on five of your scheduled days.",
        MissionMetric.SCHEDULED_DAYS_STUDIED,
        5,
        50,
    ),
    (
        "morning-session",
        "Early start",
        "Finish a study session before noon.",
        MissionMetric.EARLY_SESSION_COMPLETED,
        1,
        20,
    ),
    (
        "ten-tasks",
        "Task crusher",
        "Complete ten planned tasks.",
        MissionMetric.TASKS_COMPLETED,
        10,
        40,
    ),
    (
        "bounce-back",
        "Bounce back",
        "Return to your goal the day after missing a scheduled day.",
        MissionMetric.RECOVERED_AFTER_MISS,
        1,
        30,
    ),
]


async def seed(db: AsyncSession) -> None:
    await _seed_categories(db)
    season = await _seed_season(db)
    await _seed_missions(db, season)
    user = await _seed_demo_user(db)
    subjects = await _seed_subjects(db, user)
    await _seed_history(db, user, subjects)
    await db.commit()


async def _seed_categories(db: AsyncSession) -> None:
    existing = set((await db.execute(select(LeagueCategory.slug))).scalars())
    for order, (slug, name) in enumerate(CATEGORIES):
        if slug in existing:
            continue
        db.add(LeagueCategory(slug=slug, name=name, sort_order=order, is_active=True))
    await db.flush()


async def _seed_season(db: AsyncSession) -> LeagueSeason:
    """One active four-week season with a full division ladder."""
    result = await db.execute(
        select(LeagueSeason).where(LeagueSeason.status == SeasonStatus.ACTIVE.value)
    )
    season = result.scalars().first()
    if season is not None:
        return season

    today = datetime.now(UTC).date()
    start = today - timedelta(days=today.weekday())  # Monday of this week
    season = LeagueSeason(
        name=f"Season {start.isoformat()}",
        starts_on=start,
        ends_on=start + timedelta(weeks=4) - timedelta(days=1),
        status=SeasonStatus.ACTIVE.value,
        scoring_config=SCORING_CONFIG_V1.to_dict(),
        promotion_rate=0.2,
        relegation_rate=0.2,
    )
    db.add(season)
    await db.flush()

    categories = list((await db.execute(select(LeagueCategory))).scalars())
    for tier, name in DIVISIONS:
        division = LeagueDivision(season_id=season.id, tier=tier, name=name)
        db.add(division)
        await db.flush()
        for category in categories:
            db.add(
                LeagueCohort(
                    division_id=division.id,
                    category_id=category.id,
                    label=build_cohort_label(
                        division_name=name, category_name=category.name, group_index=0
                    ),
                    capacity=25,
                )
            )
    await db.flush()
    return season


async def _seed_missions(db: AsyncSession, season: LeagueSeason) -> None:
    existing = set(
        (
            await db.execute(select(LeagueMission.slug).where(LeagueMission.season_id == season.id))
        ).scalars()
    )
    for slug, title, description, metric, target, reward in MISSIONS:
        if slug in existing:
            continue
        db.add(
            LeagueMission(
                season_id=season.id,
                slug=slug,
                title=title,
                description=description,
                metric=metric.value,
                target=target,
                reward_points=reward,
            )
        )
    await db.flush()


async def _seed_demo_user(db: AsyncSession) -> User:
    result = await db.execute(select(User).where(func.lower(User.email) == DEMO_EMAIL))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    user = User(
        email=DEMO_EMAIL,
        password_hash=hash_password(DEMO_PASSWORD),
        auth_provider=AuthProvider.EMAIL.value,
        is_active=True,
        # The demo account is a moderator so the report queue is reachable locally.
        is_admin=True,
    )
    user.profile = UserProfile(
        username="demo_student",
        display_name="Demo Student",
        study_category="software_engineering",
        country_code="KR",
        bio="Seeded account for local development.",
    )
    user.settings = UserSettings(
        timezone="Asia/Seoul",
        daily_goal_minutes=180,
        weekly_goal_minutes=900,
        scheduled_study_days=0b0011111,  # Monday–Friday
    )
    db.add(user)
    await db.flush()
    return user


async def _seed_subjects(db: AsyncSession, user: User) -> list[Subject]:
    result = await db.execute(select(Subject).where(Subject.user_id == user.id))
    existing = list(result.scalars())
    if existing:
        return existing

    subjects = [
        Subject(user_id=user.id, name=name, color_hex=color, sort_order=order)
        for order, (name, color) in enumerate(SUBJECTS)
    ]
    db.add_all(subjects)
    await db.flush()
    return subjects


async def _seed_history(db: AsyncSession, user: User, subjects: list[Subject]) -> None:
    """Fourteen days of plausible study history, plus today's plan.

    Uses a fixed seed so every developer sees the same numbers and screenshots stay
    comparable.
    """
    existing = await db.execute(
        select(func.count()).select_from(StudySession).where(StudySession.user_id == user.id)
    )
    if existing.scalar_one() > 0:
        return

    rng = random.Random(20260722)
    today = datetime.now(UTC).date()

    for days_ago in range(14, 0, -1):
        day = today - timedelta(days=days_ago)
        # Lighter weekends: the demo data should look like a real, human week.
        is_weekend = day.weekday() >= 5
        session_count = rng.randint(0, 1) if is_weekend else rng.randint(1, 3)

        for index in range(session_count):
            subject = rng.choice(subjects)
            start_hour = 9 + index * 3 + rng.randint(0, 1)
            started = datetime(day.year, day.month, day.day, start_hour, 0, tzinfo=UTC)
            minutes = rng.choice([25, 45, 50, 60, 90])
            ended = started + timedelta(minutes=minutes)

            session = StudySession(
                id=uuid.uuid4(),
                user_id=user.id,
                subject_id=subject.id,
                source=SessionSource.TIMER.value,
                status=SessionStatus.COMPLETED.value,
                focus_mode=(
                    FocusMode.POMODORO.value if minutes <= 50 else FocusMode.STOPWATCH.value
                ),
                started_at=started,
                ended_at=ended,
                duration_seconds=minutes * 60,
                went_as_planned=rng.random() > 0.25,
                integrity_status=IntegrityStatus.OK.value,
                integrity_reasons=[],
                synced_at=ended,
            )
            session.events.append(
                StudySessionEvent(
                    id=uuid.uuid4(),
                    sequence=1,
                    event_type=SessionEventType.START.value,
                    occurred_at=started,
                    server_received_at=started,
                    payload={},
                )
            )
            session.events.append(
                StudySessionEvent(
                    id=uuid.uuid4(),
                    sequence=2,
                    event_type=SessionEventType.STOP.value,
                    occurred_at=ended,
                    server_received_at=ended,
                    payload={},
                )
            )
            db.add(session)

    await _seed_plans(db, user, subjects, today, rng)
    await db.flush()


async def _seed_plans(
    db: AsyncSession,
    user: User,
    subjects: list[Subject],
    today: date,
    rng: random.Random,
) -> None:
    titles = [
        "Review sorting algorithms",
        "Practice two SQL problems",
        "Read a system design chapter",
        "Korean vocabulary drill",
        "Refactor practice project",
        "Write session notes",
    ]
    for days_ago in (1, 0):
        day = today - timedelta(days=days_ago)
        plan = DailyPlan(user_id=user.id, plan_date=day)
        db.add(plan)
        await db.flush()

        for order in range(rng.randint(2, 4)):
            done = days_ago == 1 and rng.random() > 0.4
            db.add(
                Task(
                    id=uuid.uuid4(),
                    plan_id=plan.id,
                    subject_id=rng.choice(subjects).id,
                    title=rng.choice(titles),
                    estimated_minutes=rng.choice([20, 30, 45, 60]),
                    priority=rng.choice([p.value for p in TaskPriority]),
                    status=TaskStatus.DONE.value if done else TaskStatus.PENDING.value,
                    completed_at=(
                        datetime(day.year, day.month, day.day, 20, 0, tzinfo=UTC) if done else None
                    ),
                    sort_order=order,
                )
            )
        if days_ago == 1:
            plan.reflection = "Good focus in the morning, lost momentum after dinner."


async def main() -> None:
    configure_logging()
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as db:
            await seed(db)
        logger.info("seed_completed", email=DEMO_EMAIL, hint="Sign in with the seeded credentials.")
        print(f"\nSeeded demo account:\n  email:    {DEMO_EMAIL}\n  password: {DEMO_PASSWORD}\n")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
