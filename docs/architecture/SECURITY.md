# Security

This document describes what the code does. Where an earlier version of this file described
an intention, the intention has either been implemented or the claim removed — a security
document that overstates the system is worse than none, because it stops people looking.

## Authentication

- **Passwords:** Argon2id (pwdlib defaults), never logged. The server enforces 8–128
  characters, rejects a short denylist of the most-guessed strings, and rejects a password
  equal to the account's own username or email local part (`_reject_weak_password` in
  `app/domain/accounts/service.py`). The same rule applies at registration, on change, and
  on reset, so there is one policy rather than three.
- **Access tokens:** JWT HS256 (per-environment secret), 30 min TTL, claims `sub`, `iss`,
  `aud`, `exp`, `iat`, `jti`, `typ`. `typ` separates access tokens from realtime tickets so
  neither can be replayed as the other. Asymmetric keys are a config swap (`JWT_ALGORITHM`).
- **Refresh tokens:** opaque 256-bit values stored **hashed** (SHA-256), 30 day TTL, rotated
  on every use. Reuse of a rotated token revokes the entire family — theft detection.
- **Refresh-token transport:** chosen by the client with `X-Refresh-Transport`.
  - *body* (default) — returned in the response, for native clients that hold it in the
    platform keystore (SecureStore: Keychain/Keystore, never AsyncStorage).
  - *cookie* — set as an `HttpOnly; SameSite=Strict; Path=/api/v1/auth` cookie and **omitted
    from the response body**, for browsers. `Secure` is set in staging and production and
    omitted locally, where it would make the cookie undeliverable over `http://localhost`.
    The web dashboard uses this transport and keeps its access token in memory only, so no
    long-lived credential is reachable from JavaScript.
- **Password change** requires the current password and revokes every other session; the
  caller is re-issued one fresh pair. A change that leaves an attacker's session alive has
  not taken the account back.
- **Password reset** is a single-use, 30-minute token stored only as a SHA-256 hash. A new
  request supersedes any outstanding one. `POST /auth/forgot-password` always returns 202
  with an identical body whether or not the address is registered, so it cannot be used to
  enumerate accounts — the same reason login gives one error for both unknown email and
  wrong password. Delivery goes through the `EmailSender` protocol
  (`app/domain/accounts/email.py`); the default implementation logs, and reveals the token
  only outside deployed environments.
- **OAuth (architecture, not yet implemented):** Google/Apple map to the same `users` row
  via `(auth_provider, provider_subject)`; account linking would require a verified email
  match plus explicit user confirmation.

## Authorization

- Every private route resolves the resource **and checks ownership/membership in the query**
  (`WHERE user_id = :current_user`), not after fetch. Cross-user access returns 404, not
  403, for resources whose existence is private.
- Group and league endpoints check membership/enrolment server-side per request.
- The moderator surface is gated on `users.is_admin`, which is set out-of-band; there is no
  endpoint that grants it. Non-admins receive 404, so the surface does not confirm it exists.

## Transport & headers

TLS terminates at the load balancer in staging and production. `SecurityHeadersMiddleware`
sets, on every response including error paths:

| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `no-referrer` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |
| `Content-Security-Policy` | `default-src 'none'` (the interactive docs are exempt) |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains` — **deployed only** |

HSTS is deliberately absent locally: sending it from an HTTP origin makes the browser refuse
plain `http://localhost` afterwards.

Also at the transport layer:

- `TrustedHostMiddleware` enforces `ALLOWED_HOSTS`, blocking Host-header poisoning — which
  otherwise turns any absolute URL the app generates, password-reset links above all, into a
  link to the attacker's domain.
- `MaxBodySizeMiddleware` rejects bodies over `MAX_REQUEST_BYTES` (2 MiB default), refusing a
  declared oversize `Content-Length` outright and cutting off a chunked body as it arrives.
- CORS is an explicit per-environment allowlist, with credentials enabled so the refresh
  cookie is sent.
- `X-Request-ID` is echoed for support correlation.

## Rate limiting

Redis sliding-window counters keyed by `(bucket, caller)`, where *caller* is the
authenticated user when a valid bearer token is present and the client IP otherwise. Sliding
rather than fixed windows: a fixed window lets a caller spend `2 × limit` across a boundary,
which for login attempts is precisely the burst that matters.

| Bucket | Default | Window |
|---|---|---|
| `login`, `change-password` | 10 | 1 min |
| `refresh` | 30 | 1 min |
| `register` | 5 | 1 hour |
| `password_reset` | 5 | 1 hour |
| `social` (requests, invites, reactions, reports) | 60 | 1 min |

429 responses carry `Retry-After`.

**Client IP determination is the load-bearing part.** `X-Forwarded-For` is appended to by
each proxy, so the rightmost entries come from infrastructure we control and the leftmost is
whatever the caller sent. The limiter counts `TRUSTED_PROXY_HOPS` from the **right**, and
ignores the header entirely when that is 0. Reading the leftmost entry — the obvious
implementation — lets any caller mint a fresh bucket per request by setting one header, which
disables the limiter completely.

The limiter **fails open** if Redis is unreachable: losing the cache must not lock users out
of signing in. That trade is why `RATE_LIMIT_ENABLED` is enforced at boot rather than left
for a deployment to notice.

## Configuration safety

Deployed environments (`staging`, `production`) refuse to boot unless:

- `JWT_SECRET` is set, is not the checked-in default, and is at least 32 characters;
- `DEVICE_HASH_SALT` is set and is not the default;
- `RATE_LIMIT_ENABLED` is true;
- `ALLOWED_HOSTS` is non-empty.

Each of these fails *silently* if left wrong — a default signing key still issues
valid-looking tokens, a disabled limiter still serves traffic — so refusing to start is the
only way they become visible before an incident does. Local and test runs are unaffected.

## Input & output hygiene

- Pydantic v2 validates every request body and query; unknown fields are rejected on writes.
- Stable machine-readable error codes; internal exceptions never leak stack traces or SQL.
- User-generated text is stored raw, length-capped, and escaped at render time by clients;
  no HTML is ever interpreted.

## Secrets & config

- All secrets come from environment variables; `.env.example` contains fake values only.
- The logging processor redacts `password`, `token`, `authorization`, `secret`, and
  `device_hash` keys, so no call site has to remember.
- Separate credentials per environment; production values only in the deployment secret
  manager.

## Privacy

- Presence documents are privacy-filtered at write time (see REALTIME.md), and hidden
  presence is never stored at all.
- Device identifiers are stored only as salted HMAC hashes; raw vendor ids never persisted.
- Blocked users are excluded at query level from search, presence, groups, and rankings.
- **Account deletion** (`DELETE /me`) is two-phase. Immediately: every session is revoked,
  and the email, username, display name, bio, and avatar are released or scrubbed — so the
  address is reusable at once rather than after the retention window. Then
  `worker/jobs/account_purger.py` hard-deletes the row after a 30-day grace period, cascading
  to everything that hangs off `users.id`. The gap exists so an accidental or coerced
  deletion can be reversed, and so someone cannot erase the moderation history against them
  by deleting their account.
- The same job sweeps expired reset tokens and refresh tokens revoked more than 7 days ago.
  Recently revoked tokens are kept on purpose: reuse detection needs the row to still exist,
  or a stolen-token replay reads as an ordinary unknown token rather than a breach signal.
- Users can export everything they created (`GET /me/export`).

## Integrity & audit

- Score-affecting mutations append to `audit_logs` (append-only; no update or delete code
  path), with before/after snapshots and the actor.
- Anti-cheat thresholds live in config, not code constants, and are explained to users in
  product copy ("why was my session excluded?").

## Known gaps

Named rather than left to be discovered:

- No email verification at registration, so an address can be claimed without proving
  control of it.
- No breach-corpus password check; the denylist is short and local.
- No account lockout after repeated failed logins — the login limiter bounds the rate but
  does not lock.
- The `EmailSender` default only logs. A real provider must be wired before the reset flow
  is usable in production.
- No metrics or alerting on rate-limit hits, failed logins, or refresh-family revocations —
  the signals exist in the logs but nothing watches them.
