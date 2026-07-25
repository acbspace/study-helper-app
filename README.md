# Study League

A cross-platform study productivity app: a subject-based focus timer, daily planner, and
statistics engine, built around a seasonal league that rewards sustainable consistency —
goal completion, verified focus, and task execution — rather than raw study hours.

The system is a FastAPI backend with an ARQ background worker, an Expo / React Native mobile
app, a Vite + React web dashboard, and shared TypeScript packages (a typed API client,
request/response contracts, and design tokens). A user can sign in, create a subject, start a
study session, background or restart the app, have the running timer restored exactly, stop
the session, sync it to the server idempotently — even after being offline — and see the
resulting verified time and a daily/weekly summary.

## Features

### Study core

- **Resilient timer** — elapsed time is derived from a persisted event log, never a counter,
  so it survives backgrounding, force-quit, and reboot ([ADR-0002](docs/decisions/ADR-0002-event-sourced-timer.md)).
- **Idempotent offline sync** — client-generated ids and event sequence numbers make retries
  no-ops ([OFFLINE_SYNC.md](docs/architecture/OFFLINE_SYNC.md)).
- **Time-zone-correct statistics** — every aggregate is computed in the user's zone,
  including DST-correct day boundaries. Day, week, and yearly views, plus a calendar heatmap
  (per-day, per-month, longest streak).
- **Integrity foundation** — manual vs verified time, anomaly flagging, and an immutable audit
  log; suspicious records are flagged and explained, never silently deleted.
- **D-Day goals** — a target date with a countdown and weekly pacing measured from verified
  time, with milestones.

### Social

- **Friends** — find people by name or username, send and accept requests (a mirrored request
  auto-accepts), and block, with the friendship graph read undirected and blocking kept
  invisible to the blocked user.
- **Study groups** — create groups (public / invite-code / private), join public groups or
  redeem an invite code, invite specific users to private groups, and manage members through a
  strict owner > moderator > member role rank. Visibility, capacity, soft-deletion, and an
  owner-can't-abandon rule are enforced server-side.
- **Live presence** — a TTL'd, privacy-filtered "who's studying now" for friends and group
  members ([ADR-0005](docs/decisions/ADR-0005-presence-in-redis.md)). Hidden presence is never
  stored, hidden subjects are stripped, and blocked users disappear from both sides. Redis in
  production, an in-memory fallback for single-instance / offline dev.
- **Realtime socket** — a ticket-authenticated WebSocket at `/api/v1/realtime` with authorized
  channel subscriptions (`friends`, `group:{id}`) and Redis pub/sub fan-out, so presence
  changes and encouragement reactions arrive instantly across API instances
  ([REALTIME.md](docs/architecture/REALTIME.md)). Events only accelerate freshness — the client
  re-fetches the privacy-filtered snapshot over REST — so a dropped socket degrades to polling
  rather than showing stale data.
- **Community** — moderated topic posts with comments, reactions, bookmarks, soft-deletion,
  and reporting.

### Seasonal league

Placement into a like-for-like cohort, a weekly scoring run that turns real study activity
into 0–1000 League Points, a cohort ladder, per-component score breakdowns, missions, and
promotion/relegation at season close. Scoring is pure, versioned, and deterministic, and every
week is stored with the inputs that produced it, so a past season stays reproducible and
explainable ([ADR-0006](docs/decisions/ADR-0006-league-scoring-versioned.md)).

### Platform

- **Settings** — one screen that owns everything the account runs on: profile, daily/weekly
  goals, **scheduled study days** (the days the league's consistency score is measured
  against), pomodoro lengths, time zone, the presence and subject privacy switches, blocked
  users, a data export, and sign-out. Writes carry `expected_version`, so two devices editing
  at once produce an explicit conflict instead of a silent last-write-wins.
- **Web dashboard** — a Vite + React read-only dashboard (`apps/web`) reusing the same typed
  `api-client`, `shared-types`, and `design-tokens`, so it stays in lock-step with the API and
  matches the mobile look: verified time, streak, the week's shape, league standing, and which
  friends are studying now.
- **Notifications** — an in-app inbox (friend requests, group invites, and more) plus push
  delivery through a retryable worker job that batches to each opted-in device's Expo token
  and is idempotent per notification.
- **Moderator review queue** — an admin-gated surface (`/admin/reports/*`, gated on
  `users.is_admin`) to review reports and resolve them: dismiss, or action with content
  removal. Removals are soft-deletes, every resolution is written to the append-only audit log,
  and actioning content closes the sibling reports against it in one decision.
- **Data export** — a portable JSON export of a user's own data.
- **Focus protection** — a capability model that reports its native features as honestly
  unavailable rather than faking them (PRD §5.3).

## Repository layout

```
study-league/
├─ apps/
│  ├─ mobile/              Expo / React Native app (Expo Router, TanStack Query, Zustand)
│  └─ web/                 Vite + React dashboard (reuses packages/api-client)
├─ services/
│  ├─ api/                 FastAPI + SQLAlchemy 2.0 + Alembic (the backend)
│  └─ worker/              ARQ jobs (stale-session reaper, weekly league scoring, push delivery)
├─ packages/
│  ├─ api-client/          Typed API client (mobile + future web)
│  ├─ shared-types/        Shared request/response contracts
│  └─ design-tokens/       Colour, type, spacing, motion tokens
├─ infrastructure/docker/  Service Dockerfiles
├─ docs/                   PRD, architecture, API conventions, ADRs
├─ docker-compose.yml      PostgreSQL + Redis (and optional built API/worker)
└─ Makefile                Convenience entry points
```

## Prerequisites

- **Python 3.12+** (`py -3.12` on Windows)
- **Node.js 20+** and npm 10+
- **Docker Desktop** (for PostgreSQL + Redis; optional — the API and tests run on SQLite
  without it)

## Quick start — backend

All commands run from `services/api` unless noted. On Windows PowerShell, the venv binaries
are under `.venv\Scripts\`; on macOS/Linux use `.venv/bin/`.

### 1. Start infrastructure (optional — see note below)

```bash
docker compose up -d postgres redis        # from the repo root
```

> No Docker? Skip this. The API and the whole test suite default to SQLite, so you can run
> everything locally without a database server. Point at PostgreSQL by setting
> `DATABASE_URL` (see step 2).

### 2. Install dependencies

```bash
cd services/api
py -3.12 -m venv .venv                      # Windows;  python3.12 -m venv .venv elsewhere
.venv\Scripts\pip install -e ".[dev]"       # .venv/bin/pip on macOS/Linux
```

Optionally copy the env template and edit it:

```bash
cp .env.example .env
```

To use PostgreSQL instead of SQLite:

```bash
# PowerShell
$env:DATABASE_URL = "postgresql+asyncpg://study:study_local_pw@localhost:5432/study_league"
# bash
export DATABASE_URL="postgresql+asyncpg://study:study_local_pw@localhost:5432/study_league"
```

### 3. Run migrations

```bash
.venv\Scripts\alembic upgrade head
```

### 4. Seed development data

```bash
.venv\Scripts\python -m app.seed
```

This creates a demo account and two weeks of realistic history:

```
email:    demo@example.com
password: studyleague123
```

### 5. Start the API

```bash
.venv\Scripts\uvicorn app.main:app --reload --port 8000
```

- Health: <http://localhost:8000/api/v1/health/ready>
- Interactive docs: <http://localhost:8000/docs>
- OpenAPI schema: <http://localhost:8000/api/v1/openapi.json>

### 6. Start the worker (optional)

Requires Redis. From `services/worker`, using the API's virtualenv:

```bash
cd services/worker
..\api\.venv\Scripts\pip install -e ".[dev]"     # first time only
..\api\.venv\Scripts\python -m arq worker.main.WorkerSettings
```

## Quick start — mobile

```bash
# from the repo root — installs all JS workspaces
npm install

# start the Expo dev server
npm run --workspace apps/mobile start
```

Then press `i` (iOS simulator), `a` (Android emulator), or scan the QR code with Expo Go.

**Connecting to the API:**

- iOS simulator reaches the host at `localhost` (the default works).
- Android emulator reaches the host at `10.0.2.2` (handled automatically).
- A physical device needs your machine's LAN IP:

  ```bash
  # apps/mobile/.env
  EXPO_PUBLIC_API_BASE_URL=http://192.168.1.50:8000/api/v1
  ```

Sign in with the seeded `demo@example.com` / `studyleague123`.

## Quick start — web dashboard

```bash
# from the repo root — installs all JS workspaces
npm install

# start the Vite dev server (default http://localhost:5173)
npm run --workspace apps/web dev
```

The dashboard talks to `http://localhost:8000/api/v1` by default; point it elsewhere with an
env var:

```bash
# apps/web/.env
VITE_API_BASE_URL=https://api.example.com/api/v1
```

Sign in with the seeded `demo@example.com` / `studyleague123`.

## Testing, linting, type checking

### Backend

```bash
cd services/api
.venv\Scripts\pytest -q                 # 341 tests
.venv\Scripts\pytest -q --cov=app       # …with a coverage report
.venv\Scripts\ruff check .              # lint
.venv\Scripts\ruff format --check .     # formatting
.venv\Scripts\mypy app                  # strict type checking
.venv\Scripts\python -m scripts.openapi_snapshot --check   # API contract has not drifted
```

`ruff` and `mypy` are pinned to exact versions in `pyproject.toml`: a new lint rule in a
patch release should be a deliberate upgrade commit, not a red build on an unrelated push.

The suite runs on SQLite by default. To run it against PostgreSQL (as CI also does):

```bash
# PowerShell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://study:study_local_pw@localhost:5432/study_league_test"
.venv\Scripts\pytest -q
```

### Worker

```bash
cd services/worker
..\api\.venv\Scripts\pytest -q          # 16 tests
..\api\.venv\Scripts\ruff check .       # lint
..\api\.venv\Scripts\mypy worker        # strict type checking
```

### JavaScript workspaces

ESLint and Prettier run once at the repo root and cover `apps/*` and `packages/*`:

```bash
# from the repo root
npm run lint            # eslint (typescript-eslint + react-hooks)
npm run format:check    # prettier
npm run format          # prettier --write
```

### Mobile & shared packages

```bash
# from the repo root
npm run --workspace apps/mobile typecheck    # tsc --noEmit
npm run --workspace apps/mobile test         # 87 tests (jest-expo)
npm run coverage:mobile                      # …with a coverage report
npm run test:packages                        # 7 tests (api-client transport, vitest)
```

### Web dashboard

```bash
# from the repo root
npm run --workspace apps/web typecheck       # tsc --noEmit
npm run --workspace apps/web test            # 17 tests (vitest)
npm run --workspace apps/web build           # production bundle
```

### Regenerate the typed API client

`docs/api/openapi.json` is the checked-in contract the TypeScript types are generated from.
No running server is needed — the schema is dumped from the app in-process:

```bash
cd services/api
.venv\Scripts\python -m scripts.openapi_snapshot --write   # refresh the contract
cd ../..
npm run generate:api        # writes packages/shared-types/src/generated/api.d.ts
```

CI verifies both halves: that the snapshot still matches the application, and that
regenerating the types produces no diff. A Pydantic schema change that the clients have not
caught up with therefore fails the build instead of surfacing at runtime.

## Documentation

| Document | What it covers |
|---|---|
| [docs/product/PRD.md](docs/product/PRD.md) | Product requirements and the league mechanics |
| [docs/product/ROADMAP.md](docs/product/ROADMAP.md) | Roadmap |
| [docs/product/ASSUMPTIONS.md](docs/product/ASSUMPTIONS.md) | Decisions made without blocking |
| [docs/architecture/SYSTEM_DESIGN.md](docs/architecture/SYSTEM_DESIGN.md) | Topology, layering, source-of-truth rules |
| [docs/architecture/DATA_MODEL.md](docs/architecture/DATA_MODEL.md) | Every table and the DB-enforced invariants |
| [docs/architecture/OFFLINE_SYNC.md](docs/architecture/OFFLINE_SYNC.md) | The offline-first timer and sync protocol |
| [docs/architecture/REALTIME.md](docs/architecture/REALTIME.md) | Presence & WebSocket design |
| [docs/architecture/SECURITY.md](docs/architecture/SECURITY.md) | Auth, authorization, privacy, integrity |
| [docs/api/API_CONVENTIONS.md](docs/api/API_CONVENTIONS.md) | Errors, pagination, idempotency, versioning |
| [docs/decisions/](docs/decisions/) | Architecture Decision Records |

## Verification

Latest local run, all green:

| Check | Result |
|---|---|
| `pytest` (API, SQLite) | **341 passed**, 79% line coverage |
| `pytest` (API, PostgreSQL 16) | **341 passed** |
| `pytest` (worker) | **16 passed** |
| `ruff check` / `ruff format --check` (API + worker) | clean |
| `mypy app` / `mypy worker` (strict) | clean, 99 + 6 files |
| `scripts.openapi_snapshot --check` | contract current, 80 paths |
| `eslint .` (all JS workspaces) | clean |
| `prettier --check .` | clean |
| `tsc --noEmit` (mobile + packages) | clean |
| `jest` (mobile) | **87 passed**, 54% line coverage |
| `vitest` (api-client transport) | **7 passed** |
| `tsc --noEmit` (web) | clean |
| `vitest` (web) | **17 passed** |
| `vite build` (web) | bundles clean |
| `npm run generate:api` | no diff (types match the contract) |
| `pip-audit` | no known vulnerabilities |
| `alembic upgrade head` → seed → live API smoke test | end-to-end OK |

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs four jobs on every push:
**backend** (lint, types, contract, tests on SQLite *and* a real PostgreSQL service
container, migrations), **worker** (lint, types, tests), **frontend** (lint, formatting,
types, tests, web bundle, generated-type drift), and an advisory **audit** job
(`pip-audit`, `npm audit`) that reports without blocking.

## License

Original work created for this project. No competitor branding, assets, or copy is used.
