# ADR-0003: PostgreSQL in deployment, engine-portable models, SQLite-default tests

**Status:** accepted · **Date:** 2026-07-22

## Context
PostgreSQL is the production database. Contributors (and this repo's dev machine) may not
have Docker running; tests must be fast and always runnable.

## Decision
Models use portable SQLAlchemy types (`Uuid`, `JSON().with_variant(JSONB, "postgresql")`,
timezone-aware DateTime) and invariants both engines enforce (partial unique indexes,
CHECKs). The test suite defaults to `sqlite+aiosqlite://` per-test databases;
`TEST_DATABASE_URL` switches it to PostgreSQL, and CI runs the suite against a real
PostgreSQL service container so engine-specific behavior is exercised on every push.

## Consequences
- `make test` works with zero infrastructure; CI still proves PG compatibility.
- We forgo PG-only features (exclusion constraints, `citext`) in core tables; equivalent
  invariants use partial unique indexes + functional lower() indexes.
- Time-zone aggregation stays in domain code (portable) rather than SQL `AT TIME ZONE`.
