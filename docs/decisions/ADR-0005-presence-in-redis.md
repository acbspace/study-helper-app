# ADR-0005: Presence as TTL'd Redis documents, not database rows

**Status:** accepted · **Date:** 2026-07-22

## Context
Presence ("who is studying right now") changes every few seconds, must expire when a
device dies silently, and must never leak privacy-hidden fields. The product brief lists a
`Presence` model but also mandates ephemeral TTL semantics.

## Decision
Presence is a typed JSON document in Redis (`presence:{user_id}`, TTL 90 s) written by
session endpoints and heartbeats, with privacy filtering applied at write time. The
"model" is a Pydantic schema, not a table. REST snapshot endpoints read Redis; WebSocket
events broadcast changes; PostgreSQL is never consulted for liveness.

## Consequences
- Crash/battery-death correctness for free via TTL expiry.
- Presence is lossy by design — acceptable because durable session state lives in
  PostgreSQL and clients reconcile over REST.
- Historical "who was online" analytics, if ever needed, come from session events, not
  presence.
