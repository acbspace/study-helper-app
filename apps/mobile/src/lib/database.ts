/**
 * Local SQLite persistence for sessions and their events.
 *
 * This is the device's source of truth while offline. Every timer transition is written
 * here *before* the UI updates, which is what makes a force-quit or a dead battery
 * non-destructive: on relaunch we read the events back and recompute exactly where the
 * user was.
 *
 * Events are append-only, matching the server. Nothing here ever rewrites history.
 */

import * as SQLite from 'expo-sqlite';

import type { TimerEvent, TimerEventType } from '@/features/timer/timeline';

export type SyncState = 'local_only' | 'syncing' | 'synced' | 'rejected';

export interface LocalSession {
  id: string;
  subjectId: string;
  focusMode: 'stopwatch' | 'pomodoro';
  pomodoroFocusMinutes: number | null;
  status: 'active' | 'paused' | 'completed';
  startedAt: number;
  endedAt: number | null;
  note: string | null;
  wentAsPlanned: boolean | null;
  syncState: SyncState;
  syncMessage: string | null;
  createdAt: number;
}

const DATABASE_NAME = 'study-league.db';

let database: SQLite.SQLiteDatabase | null = null;

export async function getDatabase(): Promise<SQLite.SQLiteDatabase> {
  if (database) return database;
  database = await SQLite.openDatabaseAsync(DATABASE_NAME);
  await migrate(database);
  return database;
}

/** For tests and sign-out, so a new session starts from a clean handle. */
export function resetDatabaseHandle(): void {
  database = null;
}

async function migrate(db: SQLite.SQLiteDatabase): Promise<void> {
  await db.execAsync(`
    PRAGMA journal_mode = WAL;
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS local_sessions (
      id TEXT PRIMARY KEY NOT NULL,
      subject_id TEXT NOT NULL,
      focus_mode TEXT NOT NULL DEFAULT 'stopwatch',
      pomodoro_focus_minutes INTEGER,
      status TEXT NOT NULL,
      started_at INTEGER NOT NULL,
      ended_at INTEGER,
      note TEXT,
      went_as_planned INTEGER,
      sync_state TEXT NOT NULL DEFAULT 'local_only',
      sync_message TEXT,
      created_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS local_events (
      id TEXT PRIMARY KEY NOT NULL,
      session_id TEXT NOT NULL REFERENCES local_sessions(id) ON DELETE CASCADE,
      sequence INTEGER NOT NULL,
      event_type TEXT NOT NULL,
      occurred_at INTEGER NOT NULL,
      UNIQUE (session_id, sequence)
    );

    CREATE INDEX IF NOT EXISTS idx_sessions_sync_state ON local_sessions(sync_state);
    CREATE INDEX IF NOT EXISTS idx_events_session ON local_events(session_id, sequence);
  `);
}

interface SessionRow {
  id: string;
  subject_id: string;
  focus_mode: string;
  pomodoro_focus_minutes: number | null;
  status: string;
  started_at: number;
  ended_at: number | null;
  note: string | null;
  went_as_planned: number | null;
  sync_state: string;
  sync_message: string | null;
  created_at: number;
}

interface EventRow {
  id: string;
  session_id: string;
  sequence: number;
  event_type: string;
  occurred_at: number;
}

function toSession(row: SessionRow): LocalSession {
  return {
    id: row.id,
    subjectId: row.subject_id,
    focusMode: row.focus_mode as LocalSession['focusMode'],
    pomodoroFocusMinutes: row.pomodoro_focus_minutes,
    status: row.status as LocalSession['status'],
    startedAt: row.started_at,
    endedAt: row.ended_at,
    note: row.note,
    wentAsPlanned: row.went_as_planned === null ? null : row.went_as_planned === 1,
    syncState: row.sync_state as SyncState,
    syncMessage: row.sync_message,
    createdAt: row.created_at,
  };
}

export async function insertSession(session: LocalSession): Promise<void> {
  const db = await getDatabase();
  await db.runAsync(
    `INSERT OR REPLACE INTO local_sessions
       (id, subject_id, focus_mode, pomodoro_focus_minutes, status, started_at, ended_at,
        note, went_as_planned, sync_state, sync_message, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      session.id,
      session.subjectId,
      session.focusMode,
      session.pomodoroFocusMinutes,
      session.status,
      session.startedAt,
      session.endedAt,
      session.note,
      session.wentAsPlanned === null ? null : session.wentAsPlanned ? 1 : 0,
      session.syncState,
      session.syncMessage,
      session.createdAt,
    ],
  );
}

export async function appendEvent(
  sessionId: string,
  event: { id: string; sequence: number; eventType: TimerEventType; occurredAt: number },
): Promise<void> {
  const db = await getDatabase();
  // OR IGNORE keeps the append idempotent if a retry re-sends the same sequence.
  await db.runAsync(
    `INSERT OR IGNORE INTO local_events (id, session_id, sequence, event_type, occurred_at)
     VALUES (?, ?, ?, ?, ?)`,
    [event.id, sessionId, event.sequence, event.eventType, event.occurredAt],
  );
}

export async function updateSession(
  sessionId: string,
  changes: Partial<
    Pick<
      LocalSession,
      'status' | 'endedAt' | 'note' | 'wentAsPlanned' | 'syncState' | 'syncMessage'
    >
  >,
): Promise<void> {
  const db = await getDatabase();
  const columns: string[] = [];
  const values: (string | number | null)[] = [];

  if (changes.status !== undefined) {
    columns.push('status = ?');
    values.push(changes.status);
  }
  if (changes.endedAt !== undefined) {
    columns.push('ended_at = ?');
    values.push(changes.endedAt);
  }
  if (changes.note !== undefined) {
    columns.push('note = ?');
    values.push(changes.note);
  }
  if (changes.wentAsPlanned !== undefined) {
    columns.push('went_as_planned = ?');
    values.push(changes.wentAsPlanned === null ? null : changes.wentAsPlanned ? 1 : 0);
  }
  if (changes.syncState !== undefined) {
    columns.push('sync_state = ?');
    values.push(changes.syncState);
  }
  if (changes.syncMessage !== undefined) {
    columns.push('sync_message = ?');
    values.push(changes.syncMessage);
  }
  if (columns.length === 0) return;

  values.push(sessionId);
  await db.runAsync(`UPDATE local_sessions SET ${columns.join(', ')} WHERE id = ?`, values);
}

/** The session the user is currently in, if any. */
export async function getRunningSession(): Promise<LocalSession | null> {
  const db = await getDatabase();
  const row = await db.getFirstAsync<SessionRow>(
    `SELECT * FROM local_sessions
     WHERE status IN ('active', 'paused')
     ORDER BY started_at DESC LIMIT 1`,
  );
  return row ? toSession(row) : null;
}

export async function getSession(sessionId: string): Promise<LocalSession | null> {
  const db = await getDatabase();
  const row = await db.getFirstAsync<SessionRow>('SELECT * FROM local_sessions WHERE id = ?', [
    sessionId,
  ]);
  return row ? toSession(row) : null;
}

export async function getEvents(sessionId: string): Promise<TimerEvent[]> {
  const db = await getDatabase();
  const rows = await db.getAllAsync<EventRow>(
    'SELECT * FROM local_events WHERE session_id = ? ORDER BY sequence',
    [sessionId],
  );
  return rows.map((row) => ({
    sequence: row.sequence,
    eventType: row.event_type as TimerEventType,
    occurredAt: row.occurred_at,
  }));
}

export async function getEventRows(sessionId: string): Promise<EventRow[]> {
  const db = await getDatabase();
  return db.getAllAsync<EventRow>(
    'SELECT * FROM local_events WHERE session_id = ? ORDER BY sequence',
    [sessionId],
  );
}

export async function getNextSequence(sessionId: string): Promise<number> {
  const db = await getDatabase();
  const row = await db.getFirstAsync<{ max_sequence: number | null }>(
    'SELECT MAX(sequence) AS max_sequence FROM local_events WHERE session_id = ?',
    [sessionId],
  );
  return (row?.max_sequence ?? 0) + 1;
}

/** Sessions waiting to reach the server — the sync outbox. */
export async function getPendingSessions(): Promise<LocalSession[]> {
  const db = await getDatabase();
  const rows = await db.getAllAsync<SessionRow>(
    `SELECT * FROM local_sessions
     WHERE sync_state IN ('local_only', 'syncing')
     ORDER BY started_at`,
  );
  return rows.map(toSession);
}

export async function getRecentSessions(limit = 20): Promise<LocalSession[]> {
  const db = await getDatabase();
  const rows = await db.getAllAsync<SessionRow>(
    'SELECT * FROM local_sessions ORDER BY started_at DESC LIMIT ?',
    [limit],
  );
  return rows.map(toSession);
}

/**
 * Drop synced sessions older than the retention window.
 *
 * Synced rows are kept for a while so recent history renders offline, but the local
 * database is a cache, not an archive — the server holds the record.
 */
export async function pruneSyncedSessions(olderThanMs: number): Promise<void> {
  const db = await getDatabase();
  await db.runAsync(
    `DELETE FROM local_sessions WHERE sync_state = 'synced' AND started_at < ?`,
    [olderThanMs],
  );
}

/** Wipe local data on sign-out so accounts never share a device cache. */
export async function clearAllLocalData(): Promise<void> {
  const db = await getDatabase();
  await db.execAsync('DELETE FROM local_events; DELETE FROM local_sessions;');
}
