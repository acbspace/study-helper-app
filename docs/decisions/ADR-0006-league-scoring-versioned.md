# ADR-0006: Versioned, pure league scoring service

**Status:** accepted · **Date:** 2026-07-22

## Context
League Points are the product's trust anchor. Scores must be explainable to users,
reproducible for past seasons even after rule changes, and impossible for clients to
influence beyond their real behavior.

## Decision
`app/domain/scoring` is a pure module: `WeeklyScoreInput` (pre-aggregated facts) ×
`ScoringConfig` (weights + caps, carries `version`) → `WeeklyScoreBreakdown`. No I/O, no
clock, no randomness. Each `league_seasons` row freezes the JSON config it launched with;
`league_scores.scoring_version` records what computed each row. Weights: goal 400,
consistency 250, focus 150, tasks 150, participation 50 (config v1). Manual time
contributes zero. Hour benefits cap at the user's goal (no credit past 2× daily goal),
and scheduled rest days are excluded from consistency denominators.

## Consequences
- Deterministic unit tests define the rules before any leaderboard ships (M1 does this).
- Rule changes = new config version; old seasons re-derivable bit-for-bit.
- The worker owns computation; API endpoints only read stored breakdowns.
