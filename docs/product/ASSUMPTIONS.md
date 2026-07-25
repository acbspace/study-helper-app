# Assumptions

Decisions made without blocking on product input. Each is reversible unless noted.

## Naming & scope

1. **Repo name stays `study-helper-app`**; the product name is **Study League**. Renaming the
   repo is a GitHub operation, out of scope for code.
2. **Milestone 1 scope** is exactly the vertical slice in the brief (§12). Groups, presence,
   community, and league *endpoints* are out; league *scoring domain* and the full data model
   are in, so rankings can be exposed later without schema churn.

## Backend

3. **Python 3.12** (present on the dev machine via `py -3.12`). Code is 3.12+ compatible.
4. **Async SQLAlchemy 2.0 + asyncpg** against PostgreSQL. Tests default to **aiosqlite**
   (fast, no daemon required) and CI additionally runs the suite against real PostgreSQL.
   Models are written to be portable (SQLAlchemy `Uuid`, `JSON().with_variant(JSONB)`),
   and critical invariants use constraints supported by both engines (partial unique
   indexes, CHECK constraints). See ADR-0003.
5. **Time-zone aggregation happens in domain code**: the API converts a user-local date
   range to a UTC window, queries UTC rows, and buckets by the user's IANA time zone in
   Python. Portable, deterministic, and unit-testable; can be pushed into SQL
   (`AT TIME ZONE`) later if aggregation volume demands it.
6. **ARQ** for background jobs (Redis-native, asyncio, no extra broker). See ADR-0004.
7. **JWT access + refresh tokens** with Argon2 password hashing is the dev-friendly auth
   path. Google/Apple sign-in is architected as additional identity providers on the same
   `User` (provider + subject columns reserved), not implemented in milestone 1.
8. **Presence is not a PostgreSQL table.** It is ephemeral Redis state with a TTL, exposed
   via WebSocket + REST snapshot. The brief lists a `Presence` model; we implement it as a
   typed Redis document (schema in code) per §10's "ephemeral data with a TTL". See ADR-0005.
9. **Rate limiting** ships as a Redis token-bucket dependency applied to auth endpoints,
   disabled by default in dev/test via config. Fuller per-route budgets are backlog.

## Mobile

10. **Expo SDK 54 / React Native 0.81 / React 19** — current stable Expo line.
11. **Token-based styling system** (option explicitly allowed by the brief) instead of
    NativeWind: fewer build-time moving parts, tokens shared from `packages/design-tokens`.
12. **Wall-clock timestamps persisted at every timer transition** are the local source of
    truth; elapsed time is always derived from timestamps, never from an interval counter.
    Monotonic-clock anomalies and clock tampering are reconciled server-side
    (`server_received_at` vs claimed timestamps). See docs/architecture/OFFLINE_SYNC.md.
13. **Focus protection** ships as a platform abstraction with honest capability flags.
    On Expo-managed iOS/Android, true app-blocking requires native modules/entitlements
    (Screen Time API, UsageStats) — milestone 1 detects app-background transitions only and
    labels unsupported features as unavailable rather than faking them.

## Product mechanics

14. **Week boundaries** for statistics and league scoring are **Monday-start ISO weeks** in
    the user's time zone.
15. **Manual time earns 0 League Points** in scoring config v1 (the brief allows "reduced or
    zero"); it is always visible in personal statistics, clearly labeled.
16. **Session integrity thresholds v1** (configurable): sessions > 12h flagged; single
    running interval > 6h flagged; retroactive edits beyond 48h flagged; overlapping
    verified sessions flagged. Flagged sessions keep personal-stat credit until reviewed but
    are excluded from competitive scoring, with the exclusion surfaced to the user.
17. **League cohort size** target 25 (min 20, max 30), promotion top ~20%, relegation
    bottom ~20% — all configurable via `ScoringConfig`/season settings, not hardcoded.
18. **Currency of "verified"**: a session is *verified* when it was produced by the timer
    event stream (source = `timer`) and passed integrity checks; everything else is
    `manual` or `flagged`.
