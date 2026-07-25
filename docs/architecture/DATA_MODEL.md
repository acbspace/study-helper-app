# Data Model

UUID primary keys (client-generatable where the client must create offline: study
sessions, session events, tasks). All timestamps `TIMESTAMPTZ` UTC. `created_at` /
`updated_at` on every table. Soft deletion only where moderation/recovery demands it
(users, groups, community content); operational rows use status enums instead.

## Identity

**users** — `id`, `email` (unique, citext-lower), `password_hash` (nullable for
OAuth-only), `auth_provider` (`email`|`google`|`apple`), `provider_subject` (nullable,
unique per provider), `is_active`, `deleted_at` (soft delete).

**user_profiles** (1:1) — `username` (unique, lower), `display_name`, `avatar_url`,
`country_code`, `study_category_id` FK, `bio`.

**user_settings** (1:1) — `timezone` (IANA, default UTC), `language`, `daily_goal_minutes`,
`weekly_goal_minutes`, `scheduled_study_days` (int bitmask Mon=1<<0 … Sun=1<<6),
`privacy_show_subject`, `privacy_show_presence`, `notifications_enabled`,
`pomodoro_focus_minutes`, `pomodoro_break_minutes`, `version` (optimistic concurrency).

**devices** — `id`, `user_id`, `device_hash` (salted SHA-256 of vendor id), `platform`,
`app_version`, `last_seen_at`. Unique `(user_id, device_hash)`.

## Study

**subjects** — `id`, `user_id`, `name`, `color_hex`, `sort_order`, `is_archived`.
Unique `(user_id, lower(name)) WHERE NOT is_archived`.

**study_sessions** — `id` (client-generated UUID), `user_id`, `subject_id`,
`source` (`timer`|`manual`), `status` (`active`|`paused`|`completed`|`discarded`),
`started_at`, `ended_at`, `duration_seconds` (materialized verified elapsed),
`note`, `went_as_planned` (nullable bool), `focus_mode` (`stopwatch`|`pomodoro`),
`pomodoro_focus_minutes`, `integrity_status` (`ok`|`flagged`|`excluded`),
`integrity_reasons` (JSON list), `device_id` FK nullable, `client_created_at`,
`synced_at`, `version`.
Constraints: `ck_ended_after_started`; **partial unique index
`uq_one_running_session_per_user` ON (user_id) WHERE status IN ('active','paused')**;
`ck_duration_non_negative`; manual sessions must be `completed` with both endpoints.

**study_session_events** — `id` (client UUID), `session_id`, `sequence` (int, from 1),
`event_type` (`start`|`pause`|`resume`|`stop`), `occurred_at` (client claim),
`server_received_at`, `payload` JSON. **Unique `(session_id, sequence)`** — the
idempotency backbone. Events are append-only; no updates or deletes.

**study_goals** — `id`, `user_id`, `title`, `target_date`, `target_weekly_minutes`,
`milestones` JSON, `status`, optional `subject_ids` JSON.

## Planning

**daily_plans** — `id`, `user_id`, `plan_date` (user-local DATE), `reflection`,
unique `(user_id, plan_date)`.

**tasks** — `id` (client UUID), `plan_id`, `subject_id` nullable, `title`,
`estimated_minutes`, `priority` (`low`|`normal`|`high`), `status`
(`pending`|`done`|`deferred`), `sort_order`, `completed_at`, `deferred_to_plan_id`.

## Social (schema in M1, endpoints M2)

**friendships** — `requester_id`, `addressee_id`, `status`
(`pending`|`accepted`|`declined`|`blocked`), unique ordered pair + check
`requester_id != addressee_id`.

**study_groups** — `name`, `description`, `visibility` (`public`|`private`|`invite`),
`invite_code` (unique), `rules`, `max_members`, `owner_id`, `deleted_at`.

**group_memberships** — `group_id`, `user_id`, `role` (`owner`|`moderator`|`member`),
`joined_at`, unique `(group_id, user_id)`.

**group_invitations** — `group_id`, `inviter_id`, `invitee_id`, `status`, `expires_at`.

**Presence** — *not a table.* Redis `presence:{user_id}` JSON doc with TTL (see
REALTIME.md); REST snapshot endpoints read Redis, never PostgreSQL.

## League

**league_categories** — data-driven category list (`slug`, `name`, `is_active`) — adding
a category is an INSERT, not a deploy.

**league_seasons** — `starts_on`, `ends_on` (4 weeks), `status`
(`upcoming`|`active`|`closed`), `scoring_config` JSON (frozen copy at season start,
includes `scoring_version`), `promotion_rate`, `relegation_rate`.

**league_divisions** — `season_id`, `tier` (int: 0 Bronze … 5 Master), `name`.

**league_cohorts** — `division_id`, `category_id`, `capacity` (default 25).

**league_enrollments** — `season_id`, `user_id` (unique per season), `cohort_id` nullable,
`placement` (`provisional`|`ranked`|`unranked`), `final_rank`, `outcome`
(`promoted`|`retained`|`relegated`|`unranked`|null).

**league_scores** — `enrollment_id`, `week_index` (0–3), `points_total` (0–1000),
`computed_at`, `scoring_version`, unique `(enrollment_id, week_index)`.

**league_score_breakdowns** — `score_id` 1:1, per-component points + inputs snapshot JSON
(goal, consistency, focus, tasks, participation) so users can audit their own score.

**league_missions** — `season_id`, `slug`, `title`, `description`, `target` (int),
`metric` (enum-as-text, e.g. `planned_sessions_completed`), `reward_points`.

**user_mission_progress** — `mission_id`, `user_id`, `progress`, `completed_at`,
unique `(mission_id, user_id)`.

## Platform

**notifications** — `user_id`, `kind`, `title`, `body`, `data` JSON, `read_at`.

**reports** — `reporter_id`, `subject_type` (`user`|`group`|`post`|`comment`|`session`),
`subject_id`, `reason`, `status` (`open`|`actioned`|`dismissed`).

**audit_logs** — append-only: `actor_type` (`user`|`system`|`admin`), `actor_id`,
`action`, `entity_type`, `entity_id`, `before` JSON, `after` JSON, `reason`,
`created_at`. **No UPDATE/DELETE path exists in code**; used for every score-affecting
session change (flagging, exclusion, retro edits).

## Invariants enforced in the database

1. One running (`active`/`paused`) session per user — partial unique index.
2. Event idempotency — unique `(session_id, sequence)`.
3. `ended_at > started_at`, `duration_seconds >= 0` — CHECK.
4. One plan per `(user, date)`; one profile/settings row per user — unique FKs.
5. Season week scores unique per `(enrollment, week_index)`.
6. Username/email uniqueness case-insensitively (functional unique index on lower()).
