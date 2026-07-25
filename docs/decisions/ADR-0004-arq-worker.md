# ADR-0004: ARQ for background jobs

**Status:** accepted · **Date:** 2026-07-22

## Context
Needed: scheduled jobs (stale-session reaper, weekly league scoring, season close) and
async task execution. Redis is already in the stack. Celery brings a broker matrix and
sync worker model; Dramatiq needs RabbitMQ or Redis plus middleware; ARQ is asyncio-native
on Redis only.

## Decision
ARQ. Jobs live in `services/worker`, import domain services from the API package
(installed as a path dependency), and are idempotent (safe re-runs keyed by natural ids —
e.g., scoring keyed on `(enrollment, week_index)` upsert).

## Consequences
- One less infrastructure component; async end to end.
- ARQ's scheduling is cron-in-worker; if we outgrow it (multi-tenant schedules), swap the
  scheduler for EventBridge/Cloud cron hitting an enqueue endpoint — job bodies unchanged.
