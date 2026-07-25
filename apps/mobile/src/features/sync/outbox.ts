/**
 * The offline outbox.
 *
 * Sessions accumulate locally whenever the network is unavailable (or a live call fails)
 * and are pushed in one batch when connectivity returns. Because the server keys events by
 * `(session_id, sequence)`, pushing the same batch twice is a no-op — so this can retry
 * freely without risking double-counted study time.
 *
 * Failure is expected, not exceptional: a failed flush leaves rows exactly where they were
 * and the next attempt picks them up.
 */

import type { ApiClient, SyncResult, SyncSessionPayload } from '@study-league/api-client';
import { ApiError } from '@study-league/api-client';

import * as db from '@/lib/database';
import { newUuid } from '@/lib/uuid';

export interface FlushSummary {
  attempted: number;
  succeeded: number;
  failed: number;
  /** Server explanations for sessions excluded from competitive scoring. */
  messages: string[];
  results: SyncResult[];
}

const EMPTY_SUMMARY: FlushSummary = {
  attempted: 0,
  succeeded: 0,
  failed: 0,
  messages: [],
  results: [],
};

/** Retention for already-synced rows; older ones are pruned after a successful flush. */
const SYNCED_RETENTION_MS = 30 * 24 * 60 * 60 * 1000;

/** Build the wire payload for one locally stored session. */
export async function buildPayload(session: db.LocalSession): Promise<SyncSessionPayload | null> {
  const events = await db.getEventRows(session.id);
  // A session with no events carries no information; skip rather than send a rejectable
  // payload.
  if (events.length === 0) return null;

  return {
    id: session.id,
    subject_id: session.subjectId,
    source: 'timer',
    focus_mode: session.focusMode,
    pomodoro_focus_minutes: session.pomodoroFocusMinutes,
    note: session.note,
    went_as_planned: session.wentAsPlanned,
    client_created_at: new Date(session.createdAt).toISOString(),
    events: events.map((event) => ({
      id: event.id,
      sequence: event.sequence,
      event_type: event.event_type as SyncSessionPayload['events'][number]['event_type'],
      occurred_at: new Date(event.occurred_at).toISOString(),
    })),
  };
}

/**
 * Push every pending session to the server.
 *
 * Only *finished* sessions are sent by default: a running timer is still changing, and
 * uploading it mid-flight would just be re-sent moments later.
 */
export async function flushOutbox(
  client: ApiClient,
  options: { includeRunning?: boolean } = {},
): Promise<FlushSummary> {
  const pending = await db.getPendingSessions();
  const eligible = options.includeRunning
    ? pending
    : pending.filter((session) => session.status === 'completed');

  if (eligible.length === 0) return EMPTY_SUMMARY;

  const payloads: SyncSessionPayload[] = [];
  for (const session of eligible) {
    const payload = await buildPayload(session);
    if (payload) payloads.push(payload);
  }
  if (payloads.length === 0) return EMPTY_SUMMARY;

  for (const session of eligible) {
    await db.updateSession(session.id, { syncState: 'syncing' });
  }

  try {
    const response = await client.syncSessions(payloads, newUuid());
    const messages: string[] = [];
    let succeeded = 0;

    for (const result of response.results) {
      const accepted = result.outcome !== 'rejected';
      if (accepted) succeeded += 1;
      if (result.message) messages.push(result.message);

      await db.updateSession(result.session_id, {
        syncState: accepted ? 'synced' : 'rejected',
        syncMessage: result.message,
      });
    }

    await db.pruneSyncedSessions(Date.now() - SYNCED_RETENTION_MS);

    return {
      attempted: payloads.length,
      succeeded,
      failed: payloads.length - succeeded,
      messages,
      results: response.results,
    };
  } catch (error) {
    // Put everything back in the queue. Retryable failures (offline, 5xx) are the normal
    // case and must not lose data or alarm the user.
    for (const session of eligible) {
      await db.updateSession(session.id, { syncState: 'local_only' });
    }
    if (error instanceof ApiError && !error.isRetryable && !error.isAuthError) {
      // A permanent rejection (e.g. the subject was deleted) would loop forever otherwise.
      for (const session of eligible) {
        await db.updateSession(session.id, {
          syncState: 'rejected',
          syncMessage: error.message,
        });
      }
    }
    throw error;
  }
}

/** How many sessions are waiting to sync — drives the "pending" badge. */
export async function pendingCount(): Promise<number> {
  const pending = await db.getPendingSessions();
  return pending.filter((session) => session.status === 'completed').length;
}
