"""Domain enumerations.

Stored as short strings (not native DB enums) so adding a value is a code change without a
migration lock, and so both PostgreSQL and SQLite behave identically.
"""

from __future__ import annotations

from enum import StrEnum


class AuthProvider(StrEnum):
    EMAIL = "email"
    GOOGLE = "google"
    APPLE = "apple"


class SessionSource(StrEnum):
    TIMER = "timer"
    MANUAL = "manual"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    DISCARDED = "discarded"

    @classmethod
    def running(cls) -> tuple[SessionStatus, SessionStatus]:
        """Statuses that occupy the user's single running-session slot."""
        return (cls.ACTIVE, cls.PAUSED)


class SessionEventType(StrEnum):
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"


class FocusMode(StrEnum):
    STOPWATCH = "stopwatch"
    POMODORO = "pomodoro"


class IntegrityStatus(StrEnum):
    OK = "ok"
    FLAGGED = "flagged"
    EXCLUDED = "excluded"


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class TaskStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    DEFERRED = "deferred"


class FriendshipStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    BLOCKED = "blocked"


class GroupVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    INVITE = "invite"


class GroupRole(StrEnum):
    OWNER = "owner"
    MODERATOR = "moderator"
    MEMBER = "member"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"


class SeasonStatus(StrEnum):
    UPCOMING = "upcoming"
    ACTIVE = "active"
    CLOSED = "closed"


class EnrollmentPlacement(StrEnum):
    PROVISIONAL = "provisional"
    RANKED = "ranked"
    UNRANKED = "unranked"


class SeasonOutcome(StrEnum):
    PROMOTED = "promoted"
    RETAINED = "retained"
    RELEGATED = "relegated"
    UNRANKED = "unranked"


class MissionMetric(StrEnum):
    """Facts a mission can be measured against.

    Adding a mission is a data insert; adding a *metric* is a code change because each
    metric needs an evaluator.
    """

    PLANNED_SESSIONS_COMPLETED = "planned_sessions_completed"
    DAILY_GOAL_REACHED = "daily_goal_reached"
    SCHEDULED_DAYS_STUDIED = "scheduled_days_studied"
    EARLY_SESSION_COMPLETED = "early_session_completed"
    TASKS_COMPLETED = "tasks_completed"
    RECOVERED_AFTER_MISS = "recovered_after_miss"


class ReportSubjectType(StrEnum):
    USER = "user"
    GROUP = "group"
    POST = "post"
    COMMENT = "comment"
    SESSION = "session"


class ReportStatus(StrEnum):
    OPEN = "open"
    ACTIONED = "actioned"
    DISMISSED = "dismissed"


class ActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"
    ADMIN = "admin"


class NotificationKind(StrEnum):
    FRIEND_REQUEST = "friend_request"
    GROUP_INVITE = "group_invite"
    SESSION_FLAGGED = "session_flagged"
    LEAGUE_PROMOTED = "league_promoted"
    LEAGUE_RELEGATED = "league_relegated"
    MISSION_COMPLETED = "mission_completed"
    ENCOURAGEMENT = "encouragement"
