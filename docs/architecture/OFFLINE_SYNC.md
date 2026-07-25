# Offline & Sync Architecture

## Goals

A student on a subway or in an exam hall must be able to run full timer sessions with no
network, kill the app, restart the phone, and lose nothing. When connectivity returns,
the server converges to the same truth the device saw — and retries can never double-count.

## Client persistence (Expo SQLite)

Two tables on device:

- `local_sessions` — one row per session the device created: `id` (UUIDv4 generated on
  device), subject, mode, status, `started_at`, `ended_at`, note, flags, `sync_state`
  (`local_only` | `syncing` | `synced` | `rejected`).
- `local_events` — append-only rows `(session_id, sequence, event_type, occurred_at)`.

Every user action (start/pause/resume/stop) synchronously appends an event row **before**
updating UI state. Elapsed time is *always* recomputed from event timestamps —
`setInterval` only schedules re-renders, it never accumulates time.

### Restoration

On app launch the timer store hydrates from SQLite: if a session with status
`active`/`paused` exists, the UI resumes showing elapsed = f(events, now). This works
after backgrounding, force-kill, and device restart because nothing depended on process
memory. If the running session is older than the auto-close threshold (default 12 h), the
app offers "keep / trim / discard" instead of silently continuing.

## Sync protocol

`POST /api/v1/study-sessions/sync` with an `Idempotency-Key` header and body:

```json
{
  "sessions": [{
    "id": "client-uuid",
    "subject_id": "…",
    "source": "timer",
    "focus_mode": "pomodoro",
    "client_created_at": "…",
    "note": "…",
    "went_as_planned": true,
    "events": [
      {"id": "…", "sequence": 1, "event_type": "start", "occurred_at": "…"},
      {"id": "…", "sequence": 2, "event_type": "pause", "occurred_at": "…"}
    ]
  }]
}
```

Server behavior per session (single transaction):

1. Upsert session by client id (`user_id` from auth — a client can never write another
   user's session).
2. Insert only events whose `(session_id, sequence)` is unseen; existing sequences with
   identical content are no-ops; existing sequences with **different** content mark the
   session `flagged` (`event_conflict`) — never overwritten.
3. Re-run the timeline validator over the full event set; recompute `duration_seconds`;
   set status; stamp `server_received_at` and `synced_at`.
4. Run integrity rules (marathon length, overlap, clock skew, retro edits).
5. Respond with per-session results: `accepted` | `merged` | `flagged` | `rejected`
   (+ machine-readable reason), so the client can update `sync_state` and inform the user.

Responses are deterministic for identical payloads ⇒ network retries are safe.

### Outbox flow

```
stop/pause/resume happens ──► write event row ──► if online: live endpoint call
                                              └─► if offline/failed: leave sync_state=local_only
app foreground / connectivity regained ──► push all local_only sessions via /sync
success ──► sync_state=synced (rows kept for local stats cache, pruned after 30 days)
```

Live endpoints (`/start`, `/{id}/pause`, `/{id}/resume`, `/{id}/stop`) exist so the
server can power presence in real time; they append the *same* events the batch sync
would, through the same domain function — one code path for truth.

## Conflict cases

| Case | Resolution |
|---|---|
| Same payload retried | No-op, same response (idempotent) |
| Device A starts while device B has an active session | DB partial unique index rejects; API returns `active_session_exists` with the blocking session; client offers to stop it |
| Event sequence gap or non-monotonic timestamps | Session stored + `flagged: timeline_invalid`; user sees "excluded from competition" with reason |
| Offline session overlapping an already-synced one | Later-synced session flagged `overlap`; both kept; audit log appended |
| Clock skew (claimed time far from server receipt window) | Flag `clock_skew`; personal stats keep it, competition excludes it |

## What the client never does

- Never computes score or leaderboard values.
- Never edits or deletes an event row (append-only, matching the server).
- Never trusts its own elapsed calculation for competitive credit — the server recomputes
  from events on every sync.
