# System Design

## 1. Topology

```
┌─────────────────────────────┐
│  apps/mobile (Expo RN)      │
│  ─ Expo Router UI           │
│  ─ TanStack Query (server)  │
│  ─ Zustand (timer/UI)       │
│  ─ SQLite (sessions+outbox) │
│  ─ SecureStore (tokens)     │
└──────────┬──────────────────┘
           │ HTTPS REST /api/v1  +  WSS /api/v1/realtime (M2)
┌──────────▼──────────────────┐      ┌──────────────────┐
│  services/api (FastAPI)     │◄────►│  Redis            │
│  ─ routers (thin)           │      │  presence w/ TTL  │
│  ─ domain services (logic)  │      │  rate limits      │
│  ─ SQLAlchemy 2.0 async     │      │  ARQ job queue    │
└──────────┬──────────────────┘      └────────┬─────────┘
           │                                   │
┌──────────▼──────────────────┐      ┌────────▼─────────┐
│  PostgreSQL                 │      │ services/worker   │
│  durable state, constraints │◄────►│ (ARQ) jobs:      │
│  as invariants              │      │ session reaper,   │
└─────────────────────────────┘      │ weekly scoring    │
                                     └──────────────────┘
```

- **Monorepo:** `apps/` (clients), `services/` (deployables), `packages/` (shared
  contracts: design tokens, API types, client), `infrastructure/` (Docker), `docs/`.
- **Future web dashboard** consumes the same `packages/api-client` + REST/WS API; nothing
  in the API is mobile-shaped (no device assumptions in contracts).

## 2. Layering rules (API service)

```
app/api/*        thin HTTP: parse/validate → call domain → shape response
app/domain/*     business logic: session timeline, integrity, stats, scoring, planning
app/models/*     SQLAlchemy declarative models + DB constraints
app/schemas/*    Pydantic v2 request/response contracts
app/core/*       config, security, logging, errors, clock
app/db/*         engine/session management, portable column types
```

Rules: no business logic in routers; domain functions take explicit inputs (incl. `now`)
for determinism; DB constraints back every critical invariant the app also validates.

## 3. Source-of-truth decisions

| Data | Source of truth | Notes |
|---|---|---|
| Study time | **Session event log** (start/pause/resume/stop timestamps) | Elapsed is derived; `duration_seconds` on the session is a materialized, recomputable value |
| Active session | PostgreSQL partial unique index (`one active per user`) | Client also guards locally |
| Presence | Redis with TTL | Ephemeral; lost presence is recoverable from REST |
| League Points | Server-side scoring service, versioned config | Clients never compute scores |
| Auth | JWT access (30 min) + rotating refresh (30 days) in SecureStore | |

## 4. Time model

- Storage is **UTC everywhere** (`TIMESTAMPTZ`); presentation converts using
  `UserSettings.timezone` (IANA name).
- A "day" and Monday-start ISO "week" are computed in the user's zone; aggregation
  converts the local range to a UTC window, then buckets rows in domain code.
- Clients never compute elapsed time from `setInterval`. The mobile timer records
  transition timestamps; display ticks are cosmetic re-renders derived from timestamps.
- The server records `server_received_at` per event; large skew between claimed and
  received times feeds integrity flagging.

## 5. Offline & sync (summary — see OFFLINE_SYNC.md)

Client-generated UUIDv4 session ids + monotonically increasing event `sequence` numbers
make sync idempotent: `POST /study-sessions/sync` upserts sessions and appends only
unseen `(session_id, sequence)` events. Retries are safe; duplicates are no-ops. Live
endpoints (`start/pause/resume/stop`) and batch sync converge on the same domain function.

## 6. Real-time (summary — see REALTIME.md)

WebSocket fan-out with Redis pub/sub; presence keys carry TTLs refreshed by heartbeats;
delivery is best-effort — every durable fact is re-fetchable over REST.

## 7. Integrity pipeline

1. Every state change appends a `StudySessionEvent` (+ `server_received_at`).
2. On stop/sync, the **timeline validator** recomputes elapsed from events and rejects or
   flags impossible sequences (non-monotonic, pause-before-start, duplicate transitions).
3. The **integrity ruleset** (configurable thresholds) flags marathon sessions, overlap
   with other verified sessions, excessive retro edits, abnormal offline bursts.
4. Flags set `integrity_status` and append to `audit_logs`; nothing is silently deleted;
   excluded records surface the reason to the user.
5. Weekly scoring consumes only `verified` + unflagged sessions.

## 8. Scoring service

`app/domain/scoring/` is a pure, deterministic module: `WeeklyScoreInput` (facts) ×
`ScoringConfig` (versioned weights) → `WeeklyScoreBreakdown` (0–1000). No I/O, no clock
reads, property: monotone non-decreasing in each positive input, hard caps per component.
The worker computes scores; API reads them. Config rows persist per season for
reproducibility.

## 9. Deployment shape (AWS-compatible)

- API + worker as containers (ECS/Fargate-ready Dockerfiles in `infrastructure/docker`).
- Managed PostgreSQL (RDS) & Redis (ElastiCache). Object storage (S3) reserved for
  avatars/snapshots later. All config via environment variables (12-factor);
  `local` / `test` / `staging` / `production` env names.
- Terraform boundaries: one module per service + data stores; not written in M1.

## 10. Observability

Structured JSON logs (structlog) with `request_id` correlation propagated via contextvar
and returned as `X-Request-ID`. `/health/live` (process up) and `/health/ready`
(DB reachable) endpoints. Metrics-ready: domain services return typed results that
middleware can count/time without touching business code. Secrets and tokens never logged.

## 11. Security (summary — see SECURITY.md)

Argon2id password hashing; JWT with `aud`/`iss`/expiry; refresh rotation with reuse
detection; per-resource ownership checks in every private route; rate limiting on auth;
stable error codes without internal detail; CORS locked to known origins; device
identifiers stored only as salted hashes.
