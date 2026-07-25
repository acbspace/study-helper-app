# Security

## Authentication

- **Passwords:** Argon2id (pwdlib defaults), never logged, min length 8 with zxcvbn-style
  checks client-side; server enforces length + email format.
- **Access tokens:** JWT HS256 in M1 (per-env secret), 30 min TTL, claims: `sub` (user
  id), `iss`, `aud`, `exp`, `iat`, `jti`. Asymmetric keys are a config swap
  (`JWT_ALGORITHM`), planned before any third-party consumers.
- **Refresh tokens:** opaque random 256-bit values, stored **hashed** (SHA-256) in
  `refresh_tokens` with device binding, 30 day TTL, rotated on every use; reuse of a
  rotated token revokes the whole family (theft detection).
- **Mobile storage:** tokens only in SecureStore (Keychain/Keystore), never AsyncStorage.
- **OAuth (architecture):** Google/Apple map to the same `users` row via
  `(auth_provider, provider_subject)`; account linking requires a verified email match +
  explicit user confirmation.

## Authorization

- Every private route resolves the resource **and checks ownership/membership in the
  query** (`WHERE user_id = :current_user`), not after fetch. Cross-user access returns
  404 (not 403) for resources whose existence is private.
- Group/league endpoints check membership/enrollment server-side per request.
- No admin backdoors in API code paths; moderation actions go through audited endpoints.

## Transport & headers

TLS-only in staging/production (enforced at the load balancer); HSTS; CORS allowlist per
environment; `X-Request-ID` echoed for support correlation.

## Rate limiting

Redis token bucket keyed by `(route_class, ip)` and `(route_class, user_id)`; enabled per
environment. Auth endpoints get the tightest budgets (login 10/min/ip). 429 responses
carry `Retry-After`.

## Input & output hygiene

- Pydantic v2 validates every request body/query; unknown fields rejected on writes.
- Stable machine-readable error codes; internal exceptions never leak stack traces or SQL.
- User-generated text (notes, names, reflections) is stored raw, length-capped, and
  escaped at render time by clients; no HTML is ever interpreted.

## Secrets & config

- All secrets via environment variables; `.env.example` contains fake values only.
- No secrets in logs: logging processor redacts `password`, `token`, `authorization`,
  `secret` keys.
- Separate credentials per environment; production values only in the deployment secret
  manager (SSM/Secrets Manager).

## Privacy

- Presence documents are privacy-filtered at write time (see REALTIME.md).
- Device identifiers stored only as salted hashes; raw vendor ids never persisted.
- Soft-deleted users disappear from search/presence immediately; hard purge job (30 days)
  is scheduled work in M2.
- Blocked users are excluded at query level from search, presence, groups, and rankings.

## Integrity & audit

- Score-affecting mutations append to `audit_logs` (append-only; no update/delete code
  path). Includes before/after snapshots and actor.
- Anti-cheat thresholds live in config, not code constants, and are documented to users
  in product copy ("why was my session excluded?").
