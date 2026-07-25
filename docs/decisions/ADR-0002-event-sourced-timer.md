# ADR-0002: Event-log timer with derived durations

**Status:** accepted · **Date:** 2026-07-22

## Context
Study time is the competitive currency. Interval counters drift, die with the process, and
are trivially falsifiable. Sessions must survive app kill/restart and offline periods, and
sync must be retry-safe.

## Decision
Every session is an append-only event stream (`start`/`pause`/`resume`/`stop`) with client
timestamps, client-generated UUIDs, and per-session `sequence` numbers. Elapsed time is
derived by a pure timeline function on both client and server; the server's derivation is
authoritative for competition. `(session_id, sequence)` uniqueness makes sync idempotent.
`duration_seconds` on the session row is a materialized cache, recomputable at any time.

## Consequences
- Restoration, offline sync, integrity checking, and auditability fall out of one design.
- Storage cost: ~4–10 event rows per session — negligible.
- Server must guard against event conflicts (same sequence, different content) → flagging
  path, never overwrite.
