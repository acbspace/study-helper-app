# API Conventions

Base path: `/api/v1`. OpenAPI at `/api/v1/openapi.json`, interactive docs at `/docs`
(non-production only).

## Requests

- JSON bodies, `snake_case` fields, UTC ISO-8601 timestamps with `Z` suffix.
- Auth: `Authorization: Bearer <access token>`.
- Retry-sensitive writes (`/study-sessions/sync`, future purchases) accept an
  `Idempotency-Key` header; the same key + same payload returns the stored response.
- Optional `X-Device-Id` header: an opaque client-generated installation id; the server
  stores only a salted hash.

## Responses

- Success: resource or `{"items": [...], "next_cursor": "..."} ` for collections.
- Cursor pagination for feeds/large lists: `?cursor=<opaque>&limit=50` (max 100). Cursors
  are base64 of `(sort_key, id)`; stable under inserts.
- Errors — always this envelope with a **stable machine code**:

```json
{
  "error": {
    "code": "active_session_exists",
    "message": "You already have a running session.",
    "details": {"session_id": "…"}
  }
}
```

| HTTP | Meaning | Example codes |
|---|---|---|
| 400 | Validation / bad state transition | `validation_error`, `invalid_transition` |
| 401 | Missing/expired credentials | `not_authenticated`, `token_expired` |
| 403 | Authenticated but not allowed | `not_permitted` |
| 404 | Missing or not yours (private resources) | `subject_not_found`, `session_not_found` |
| 409 | Conflict with current state | `active_session_exists`, `duplicate_username`, `version_conflict` |
| 422 | Well-formed but semantically impossible | `timeline_invalid` |
| 429 | Rate limited | `rate_limited` (+ `Retry-After`) |

- Every response carries `X-Request-ID` (echoing the request's, else generated).

## Versioning

- Path-versioned (`/api/v1`). Additive changes (new optional fields/endpoints) don't bump
  the version. Breaking changes ship as `/api/v2` alongside `/api/v1` with a deprecation
  window. Mobile clients send `X-Client-Version`; the server can respond
  `426 upgrade_required` for retired clients.

## Naming

- Resources are plural nouns (`/subjects`, `/study-sessions`). State transitions are verb
  sub-resources (`/study-sessions/{id}/pause`) because they are commands with rules, not
  field patches.
- Times in responses that are user-facing aggregates (e.g., `today`) always state the
  time zone used: `{"date": "2026-07-22", "timezone": "Asia/Seoul", ...}`.

## Client generation

`packages/shared-types` mirrors the OpenAPI schemas; `npm run generate:api` (root)
regenerates TypeScript types from the running API's `/api/v1/openapi.json` via
`openapi-typescript`. `packages/api-client` wraps fetch with auth, retries, idempotency
keys, and typed endpoints consumed by mobile (and the future web dashboard).
