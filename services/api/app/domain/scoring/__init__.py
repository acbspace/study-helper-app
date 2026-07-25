"""League scoring.

Pure domain: `WeeklyScoreInput` × `ScoringConfig` → `WeeklyScoreBreakdown`. No I/O, no
clock, no randomness — the same inputs always produce the same score, which is what makes
past seasons reproducible and disputes resolvable.
"""

from app.domain.scoring.config import SCORING_CONFIG_V1, ScoringConfig, ScoringWeights
from app.domain.scoring.models import (
    ComponentScore,
    DayActivity,
    WeeklyScoreBreakdown,
    WeeklyScoreInput,
)
from app.domain.scoring.service import score_week

__all__ = [
    "SCORING_CONFIG_V1",
    "ComponentScore",
    "DayActivity",
    "ScoringConfig",
    "ScoringWeights",
    "WeeklyScoreBreakdown",
    "WeeklyScoreInput",
    "score_week",
]
