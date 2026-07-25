# ADR-0001: Monorepo with npm workspaces + per-service Python project

**Status:** accepted · **Date:** 2026-07-22

## Context
Mobile app (TypeScript), API + worker (Python), and shared contracts must evolve together;
a future web client will reuse the API client and design tokens.

## Decision
Single repo. npm workspaces manage JS packages (`apps/mobile`, `packages/*`). Python
services (`services/api`, `services/worker`) each own a `pyproject.toml` and virtualenv —
no cross-language build tool (Nx/Bazel) yet.

## Consequences
- One PR can change API + contract + client coherently; CI runs per-package jobs.
- Cost: contributors need both toolchains; mitigated by Makefile entry points.
- If JS package count grows, we can adopt Turborepo without restructuring.
