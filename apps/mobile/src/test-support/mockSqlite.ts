/**
 * Minimal in-memory stand-in for expo-sqlite.
 *
 * Deliberately executes against real data structures rather than returning canned values,
 * so the tests exercise the app's actual persistence logic — including sequence numbering
 * and the "insert or ignore" idempotency the outbox depends on.
 */

interface SessionRecord {
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

interface EventRecord {
  id: string;
  session_id: string;
  sequence: number;
  event_type: string;
  occurred_at: number;
}

export interface MockDatabase {
  execAsync(sql: string): Promise<void>;
  runAsync(sql: string, params?: unknown[]): Promise<{ changes: number }>;
  getFirstAsync<T>(sql: string, params?: unknown[]): Promise<T | null>;
  getAllAsync<T>(sql: string, params?: unknown[]): Promise<T[]>;
  /** Test helper: inspect raw state. */
  __state(): { sessions: SessionRecord[]; events: EventRecord[] };
}

export function createMockDatabase(): MockDatabase {
  const sessions = new Map<string, SessionRecord>();
  const events: EventRecord[] = [];

  const normalise = (sql: string): string => sql.replace(/\s+/g, ' ').trim().toUpperCase();

  return {
    async execAsync(sql: string) {
      const upper = normalise(sql);
      if (upper.includes('DELETE FROM LOCAL_EVENTS')) events.length = 0;
      if (upper.includes('DELETE FROM LOCAL_SESSIONS')) sessions.clear();
    },

    async runAsync(sql: string, params: unknown[] = []) {
      const upper = normalise(sql);

      if (upper.startsWith('INSERT OR REPLACE INTO LOCAL_SESSIONS')) {
        const [
          id,
          subject_id,
          focus_mode,
          pomodoro_focus_minutes,
          status,
          started_at,
          ended_at,
          note,
          went_as_planned,
          sync_state,
          sync_message,
          created_at,
        ] = params as [
          string,
          string,
          string,
          number | null,
          string,
          number,
          number | null,
          string | null,
          number | null,
          string,
          string | null,
          number,
        ];
        sessions.set(id, {
          id,
          subject_id,
          focus_mode,
          pomodoro_focus_minutes,
          status,
          started_at,
          ended_at,
          note,
          went_as_planned,
          sync_state,
          sync_message,
          created_at,
        });
        return { changes: 1 };
      }

      if (upper.startsWith('INSERT OR IGNORE INTO LOCAL_EVENTS')) {
        const [id, session_id, sequence, event_type, occurred_at] = params as [
          string,
          string,
          number,
          string,
          number,
        ];
        // Mirrors the UNIQUE (session_id, sequence) constraint.
        const duplicate = events.some(
          (event) => event.session_id === session_id && event.sequence === sequence,
        );
        if (duplicate) return { changes: 0 };
        events.push({ id, session_id, sequence, event_type, occurred_at });
        return { changes: 1 };
      }

      if (upper.startsWith('UPDATE LOCAL_SESSIONS SET')) {
        const sessionId = params[params.length - 1] as string;
        const session = sessions.get(sessionId);
        if (!session) return { changes: 0 };

        // Column order in the generated SQL matches the values array.
        const assignments = sql
          .slice(sql.indexOf('SET') + 3, sql.indexOf('WHERE'))
          .split(',')
          .map((part) => part.trim().split('=')[0]!.trim());

        assignments.forEach((column, index) => {
          const value = params[index];
          (session as unknown as Record<string, unknown>)[column] = value;
        });
        return { changes: 1 };
      }

      if (upper.startsWith('DELETE FROM LOCAL_SESSIONS')) {
        const cutoff = params[0] as number;
        for (const [id, session] of sessions) {
          if (session.sync_state === 'synced' && session.started_at < cutoff) {
            sessions.delete(id);
          }
        }
        return { changes: 1 };
      }

      return { changes: 0 };
    },

    async getFirstAsync<T>(sql: string, params: unknown[] = []): Promise<T | null> {
      const upper = normalise(sql);

      if (upper.includes('MAX(SEQUENCE)')) {
        const sessionId = params[0] as string;
        const matching = events.filter((event) => event.session_id === sessionId);
        const max = matching.length ? Math.max(...matching.map((event) => event.sequence)) : null;
        return { max_sequence: max } as T;
      }

      if (upper.includes("STATUS IN ('ACTIVE', 'PAUSED')")) {
        const running = [...sessions.values()]
          .filter((session) => session.status === 'active' || session.status === 'paused')
          .sort((a, b) => b.started_at - a.started_at);
        return (running[0] ?? null) as T | null;
      }

      if (upper.includes('FROM LOCAL_SESSIONS WHERE ID = ?')) {
        return (sessions.get(params[0] as string) ?? null) as T | null;
      }

      return null;
    },

    async getAllAsync<T>(sql: string, params: unknown[] = []): Promise<T[]> {
      const upper = normalise(sql);

      if (upper.includes('FROM LOCAL_EVENTS WHERE SESSION_ID = ?')) {
        return events
          .filter((event) => event.session_id === params[0])
          .sort((a, b) => a.sequence - b.sequence) as T[];
      }

      if (upper.includes("SYNC_STATE IN ('LOCAL_ONLY', 'SYNCING')")) {
        return [...sessions.values()]
          .filter(
            (session) => session.sync_state === 'local_only' || session.sync_state === 'syncing',
          )
          .sort((a, b) => a.started_at - b.started_at) as T[];
      }

      if (upper.includes('FROM LOCAL_SESSIONS ORDER BY STARTED_AT DESC')) {
        return [...sessions.values()].sort((a, b) => b.started_at - a.started_at) as T[];
      }

      return [];
    },

    __state() {
      return { sessions: [...sessions.values()], events: [...events] };
    },
  };
}
