/**
 * Offline outbox: queue durability and idempotent flushing.
 */

import type { ApiClient, SyncResult } from '@study-league/api-client';
import { ApiError } from '@study-league/api-client';

import * as db from '@/lib/database';
import { resetDatabaseHandle } from '@/lib/database';
import { useTimerStore } from '@/features/timer/timerStore';

import { flushOutbox, pendingCount } from '../outbox';

/** A minimal client stub recording the payloads it receives. */
function makeClient(handler: (sessions: unknown[]) => Promise<{ results: SyncResult[] }>): {
  client: ApiClient;
  calls: unknown[][];
} {
  const calls: unknown[][] = [];
  const client = {
    syncSessions: jest.fn(async (sessions: unknown[]) => {
      calls.push(sessions);
      return handler(sessions);
    }),
  } as unknown as ApiClient;
  return { client, calls };
}

function result(sessionId: string, outcome: SyncResult['outcome'] = 'accepted'): SyncResult {
  return {
    session_id: sessionId,
    outcome,
    status: 'completed',
    duration_seconds: 1500,
    integrity_status: outcome === 'flagged' ? 'flagged' : 'ok',
    reasons: [],
    message: outcome === 'flagged' ? 'This session was flagged.' : null,
  };
}

async function completeOneSession(): Promise<string> {
  const store = useTimerStore.getState();
  const id = await store.start({ subjectId: 'subject-1' });
  await store.stop();
  store.reset();
  return id!;
}

beforeEach(async () => {
  resetDatabaseHandle();
  await db.clearAllLocalData();
  useTimerStore.getState().reset();
});

describe('outbox', () => {
  it('counts only completed sessions as pending', async () => {
    // A running session is not eligible for sync.
    await useTimerStore.getState().start({ subjectId: 'subject-1' });
    expect(await pendingCount()).toBe(0);

    await useTimerStore.getState().stop();
    useTimerStore.getState().reset();
    expect(await pendingCount()).toBe(1);
  });

  it('flushes a completed session and marks it synced', async () => {
    const sessionId = await completeOneSession();
    const { client, calls } = makeClient(async () => ({ results: [result(sessionId)] }));

    const summary = await flushOutbox(client);

    expect(summary.succeeded).toBe(1);
    expect(calls).toHaveLength(1);
    const stored = await db.getSession(sessionId);
    expect(stored?.syncState).toBe('synced');
    expect(await pendingCount()).toBe(0);
  });

  it('is idempotent: a second flush sends nothing', async () => {
    const sessionId = await completeOneSession();
    const { client, calls } = makeClient(async () => ({ results: [result(sessionId)] }));

    await flushOutbox(client);
    const second = await flushOutbox(client);

    expect(second.attempted).toBe(0);
    expect(calls).toHaveLength(1); // no second network call
  });

  it('re-queues sessions when the network fails, losing nothing', async () => {
    const sessionId = await completeOneSession();
    const { client } = makeClient(async () => {
      throw ApiError.network(new Error('offline'));
    });

    await expect(flushOutbox(client)).rejects.toBeInstanceOf(ApiError);

    // The session is back in the queue for the next attempt.
    const stored = await db.getSession(sessionId);
    expect(stored?.syncState).toBe('local_only');
    expect(await pendingCount()).toBe(1);
  });

  it('recovers on a later flush after a transient failure', async () => {
    const sessionId = await completeOneSession();
    let attempts = 0;
    const { client } = makeClient(async () => {
      attempts += 1;
      if (attempts === 1) throw ApiError.network(new Error('offline'));
      return { results: [result(sessionId)] };
    });

    await expect(flushOutbox(client)).rejects.toBeTruthy();
    const summary = await flushOutbox(client);

    expect(summary.succeeded).toBe(1);
    expect((await db.getSession(sessionId))?.syncState).toBe('synced');
  });

  it('surfaces server messages for flagged sessions without deleting them', async () => {
    const sessionId = await completeOneSession();
    const { client } = makeClient(async () => ({ results: [result(sessionId, 'flagged')] }));

    const summary = await flushOutbox(client);

    expect(summary.messages).toContain('This session was flagged.');
    // Flagged is still accepted and kept locally.
    expect((await db.getSession(sessionId))?.syncState).toBe('synced');
  });

  it('marks a session rejected on a permanent (non-retryable) error', async () => {
    const sessionId = await completeOneSession();
    const { client } = makeClient(async () => {
      throw new ApiError(404, 'subject_not_found', 'Subject not found.');
    });

    await expect(flushOutbox(client)).rejects.toBeTruthy();
    // A permanent failure must not loop forever in the queue.
    const stored = await db.getSession(sessionId);
    expect(stored?.syncState).toBe('rejected');
    expect(await pendingCount()).toBe(0);
  });

  it('batches multiple pending sessions into one request', async () => {
    await completeOneSession();
    await completeOneSession();
    const { client, calls } = makeClient(async (sessions) => ({
      results: (sessions as { id: string }[]).map((session) => result(session.id)),
    }));

    const summary = await flushOutbox(client);

    expect(summary.attempted).toBe(2);
    expect(calls).toHaveLength(1);
    expect((calls[0] as unknown[]).length).toBe(2);
  });
});
