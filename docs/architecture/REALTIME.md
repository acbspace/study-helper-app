# Real-time Architecture

> **Status: implemented.** Presence (`app/domain/social/presence.py`, `GET /api/v1/presence/*`)
> is TTL'd and privacy-filtered, with a Redis backend and an in-memory fallback. The transport
> (`app/domain/realtime/`, `WS /api/v1/realtime`) is live: ticket auth, authorized channel
> subscriptions, Redis pub/sub fan-out, and `presence.changed` / `reaction.created` events.
> Clients still poll the REST snapshots as the standing fallback.
>
> Deviations from the sketch below, and why:
> - **Channels are per-recipient.** `friends` resolves server-side to the concrete channel
>   `friends:{subscriber_id}`; a producer publishes to each *recipient's* channel. This keeps
>   authorization trivial (you can only ever be given your own feed) and needs no filtering on
>   the read side.
> - **Events are thin.** They carry a user summary and a state, never durable data, because
>   the client re-fetches the privacy-filtered snapshot. An event therefore cannot leak what a
>   snapshot would hide.
> - **Exactly-once local delivery.** With Redis, a publish goes *only* to Redis and comes back
>   to every instance (including the publisher) through one subscriber loop, so no message is
>   delivered twice. Without Redis the broadcaster delivers to the local hub directly.
> - `leaderboard.updated` and `group.member_updated` are not emitted yet (M3 / later).

## Principles

1. **Ephemeral over WebSocket, durable over REST.** Anything a user must not lose is
   persisted and fetchable; the socket only accelerates freshness.
2. **Presence lives in Redis with a TTL** — losing Redis loses nothing durable.
3. **Delivery is best-effort.** Clients reconcile on reconnect by re-fetching snapshots;
   no server-side replay guarantees.

## Presence model

Key: `presence:{user_id}` → JSON:

```json
{
  "state": "studying" | "break" | "idle",
  "session_id": "…",
  "subject_id": "…",          // omitted when privacy_show_subject = false
  "started_at": "…",
  "updated_at": "…"
}
```

TTL 90 s, refreshed by client heartbeat every 30 s and by any session event. Key expiry =
offline. Privacy settings are applied **at write time** (the doc simply never contains
what the user hides) so no consumer can leak it.

Group room membership: `room:group:{group_id}` Redis set of user ids with the same TTL
discipline.

## Transport

`WS /api/v1/realtime?token=<short-lived ws ticket>` — a ticket minted over REST from the
access token (avoids putting long-lived JWTs in URLs). One socket per app instance;
client subscribes to channels:

```
{"op": "subscribe", "channels": ["group:abc", "friends"]}
```

## Events (server → client)

| Event | Payload |
|---|---|
| `user.study_started` | user_id, subject_id?, started_at |
| `user.study_paused` / `user.study_stopped` | user_id, verified_seconds_today |
| `user.presence_changed` | user_id, state |
| `group.member_updated` | group_id, member summary |
| `leaderboard.updated` | scope, top deltas (ids + points only) |
| `reaction.created` | from_user_id, target, emoji-slug |

Fan-out: API instances publish to Redis pub/sub channel per scope; each instance forwards
to its locally connected sockets. Horizontal scale = more API instances, no sticky
sessions required beyond the socket itself.

## What presence events never contain

Email, real name, device info, precise location/timezone, note contents, or any field the
user's privacy settings hide. Payloads carry ids + display-safe fields only.

## Failure behavior

- Socket drop → client falls back to REST polling (30 s) with jitter, resubscribes on
  reconnect, re-fetches group/friend snapshots.
- Redis down → presence endpoints return empty-but-healthy responses; timers and sync are
  unaffected (PostgreSQL path has no Redis dependency).
