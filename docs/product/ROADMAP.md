# Roadmap

## M1 — Foundation & timer vertical slice (this milestone) ✅ in repo

- Monorepo, Docker Compose (PostgreSQL + Redis), Makefile, CI (lint, types, tests).
- FastAPI service: health/readiness, JWT auth (email/password), profile & settings,
  subject CRUD, study-session lifecycle (start/pause/resume/stop), idempotent offline
  sync, manual entries, daily/weekly statistics with time-zone correctness, daily plans &
  tasks, seed data.
- Full database schema (incl. social + league tables) via Alembic.
- League scoring domain service — deterministic, versioned, unit-tested, **not yet
  exposed** via rankings endpoints.
- Worker (ARQ): stale-session auto-close reaper.
- Mobile (Expo): auth, onboarding basics, subjects, resilient offline-first timer with
  SQLite persistence + restoration, sync outbox, Today dashboard, Insights (day/week),
  tasks. Jest tests for timer machine, offline queue, screens.
- **Settings arrived late.** The `user_settings` columns shipped in M1 and drove real
  behaviour from the start — scheduled study days feed the league's consistency score, the
  privacy flags gate presence — but no client could write them, so every account ran on its
  registration defaults. The Settings screen (`apps/mobile/src/screens/SettingsScreen.tsx`)
  closes that gap.

## M2 — Social & presence ✅ in repo

- **Friends (in repo)** — search/request/accept/decline/cancel/unfriend/block/unblock, with
  an undirected friendship read model and blocking that is invisible to the blocked user.
  Backend (`app/domain/social/service.py`), typed client, and a live Friends tab.
- **Groups (in repo)** — create/update/delete (soft), public/invite/private visibility,
  invite codes, join by code, personal invitations, membership, and an owner > moderator >
  member role rank with capacity limits. Backend (`app/domain/social/groups.py`), typed
  client, and a live Groups tab.
- **Reporting (in repo)** — report a user or group with a reason, one open report per
  subject, subjects validated so the moderation queue never holds dangling ids
  (`app/domain/platform/reports.py`). Blocklist filtering is applied on every social read.
- **Presence (in repo)** — TTL'd, privacy-filtered presence for friends and group members
  with heartbeats and blocklist filtering (`app/domain/social/presence.py`), a Redis backend
  with an in-memory fallback, a typed client, and a live "studying now" indicator on the
  Friends tab driven by the timer.
- **Realtime socket (in repo)** — ticket-authenticated `WS /api/v1/realtime`, authorized
  channel subscriptions, Redis pub/sub fan-out across instances, `presence.changed` and
  `reaction.created` events, and a reconnecting mobile client (`app/domain/realtime/`,
  `apps/mobile/src/features/realtime/`). REST polling remains the fallback.
- **Notifications (in repo)** — durable in-app inbox with unread counts and read state,
  produced on friend requests/acceptance and group invitations, plus Expo push-token
  registration per device (`app/domain/platform/notifications.py`). **Push delivery** is a
  retryable worker job (`worker/jobs/push_notifier.py`) over `PushService`: it batches pending
  notifications to each opted-in device's Expo token, is idempotent via a `pushed_at` marker,
  and leaves a row unpushed for retry if the provider is unreachable.
  The **client half arrived late**: until the inbox screen, the header badge, and
  `usePushRegistration` existed, no client ever called `PUT /me/push-token`, so the delivery
  job ran every two minutes against a permanently empty set of tokens.
- **Reporting UI (in repo)** — `ReportButton` on users, groups, and posts. The moderation
  pipeline was complete server-side from M2 but had no entrance, so the queue could not
  receive anything.
- **Rate limiting (in repo)** — a shared bucket across social writes (requests, invites,
  reactions, reports); blocklist enforcement on every social read.

## M3 — Leagues ✅ in repo

- **Season lifecycle** — placement into a like-for-like cohort (category + entry division,
  cohorts capped at 20–30 and created on demand), provisional placement for new users, and
  close-out that ranks each cohort and assigns promotion/retention/relegation — with inactive
  users marked *unranked* rather than relegated (`app/domain/league/service.py`).
- **Weekly scoring run** — real activity → `WeeklyScoreInput` → the pure scorer → stored
  points and per-component breakdowns (`app/domain/league/facts.py`). Idempotent: it upserts
  by `(enrollment, week)`, so a retried job re-derives rather than accumulates. Scheduled
  hourly in the worker (`worker/jobs/league_scorer.py`).
- **League endpoints** — enroll, current standing, cohort leaderboard, score breakdown,
  missions, season history; league UI on the mobile League tab (standing, ladder, breakdown,
  missions) with "no season" / "not enrolled" as first-class states.
- **Mission engine** — driven by `league_missions.metric` over the same weekly facts, so a
  new mission is a data insert and only a new *metric* needs code
  (`app/domain/league/missions.py`).
- Still open: an anti-cheat review queue for moderators (exclusion explanations already reach
  the user through the score breakdown).

## M4 — Depth & expansion ✅ mostly in repo

- **D-Day goals (in repo)** — target date + weekly commitment + milestones, with a countdown
  and weekly pacing from verified time (`app/domain/goals/`), and a Goals screen.
- **Yearly insights (in repo)** — per-day calendar heatmap, per-month totals, active days and
  longest streak (`GET /statistics/yearly`), surfaced on the Insights tab.
- **Community (in repo)** — moderated topic posts, comments, reactions, and bookmarks with
  soft-deletion and report integration (`app/domain/community/`, migration `0003`), and a
  Community screen.
- **Data export (in repo)** — a portable JSON copy of the user's own data (`GET /me/export`).
- **Web dashboard (in repo)** — a Vite + React read-only dashboard (`apps/web`) reusing the
  shared `api-client` / `shared-types` / `design-tokens`: sign-in, verified time, streak, the
  week's shape, league standing, and live friend presence. Vitest + tsc in CI.
- **Focus protection (in repo, abstraction only)** — an honest capability model that reports
  app-blocking / distraction-alerts / background-detection as unavailable with reasons; the
  native Screen Time / UsageStats modules and opt-in camera check-in remain future work.
- **Moderator review queue (in repo)** — admin-gated report review and resolution
  (`app/domain/platform/moderation.py`, `/admin/reports`): dismiss or action with soft-delete,
  every decision audit-logged, sibling reports closed on content removal.
- Still open: the native focus-protection modules and opt-in camera check-in.

## Continuous

- Accessibility audits per screen; performance budgets (cold start < 2 s, timer
  restoration < 300 ms); load testing sync endpoints; chaos testing offline paths.
