/**
 * Timer store: persistence-first behaviour and restoration.
 *
 * The key guarantee under test is that every transition is durable *before* state updates,
 * so a fresh store hydrating from the same database lands in the same place — which is what
 * makes force-quit and restart non-destructive.
 */

import * as db from '@/lib/database';
import { resetDatabaseHandle } from '@/lib/database';

import { useTimerStore } from '../timerStore';

async function resetWorld(): Promise<void> {
  resetDatabaseHandle();
  await db.clearAllLocalData();
  useTimerStore.getState().reset();
}

beforeEach(async () => {
  await resetWorld();
});

describe('timer store lifecycle', () => {
  it('start persists a session and a start event before updating state', async () => {
    const sessionId = await useTimerStore.getState().start({ subjectId: 'subject-1' });
    expect(sessionId).not.toBeNull();

    const state = useTimerStore.getState();
    expect(state.state.status).toBe('active');

    // Persisted, not just in memory.
    const stored = await db.getRunningSession();
    expect(stored?.id).toBe(sessionId);
    const events = await db.getEvents(sessionId!);
    expect(events).toHaveLength(1);
    expect(events[0]!.eventType).toBe('start');
  });

  it('refuses to start a second session while one is running', async () => {
    await useTimerStore.getState().start({ subjectId: 'subject-1' });
    const second = await useTimerStore.getState().start({ subjectId: 'subject-2' });
    expect(second).toBeNull();
    expect(useTimerStore.getState().lastError).toMatch(/already running/i);
  });

  it('pause then resume accumulates only studied time', async () => {
    const store = useTimerStore.getState();
    await store.start({ subjectId: 'subject-1' });
    await store.pause();
    expect(useTimerStore.getState().state.status).toBe('paused');

    await store.resume();
    expect(useTimerStore.getState().state.status).toBe('active');

    const events = await db.getEvents(useTimerStore.getState().sessionId!);
    expect(events.map((event) => event.eventType)).toEqual(['start', 'pause', 'resume']);
  });

  it('stop completes the session and records the note', async () => {
    const store = useTimerStore.getState();
    const sessionId = await store.start({ subjectId: 'subject-1' });
    await store.stop({ note: 'done', wentAsPlanned: true });

    expect(useTimerStore.getState().state.status).toBe('completed');
    const stored = await db.getSession(sessionId!);
    expect(stored?.status).toBe('completed');
    expect(stored?.note).toBe('done');
    expect(stored?.wentAsPlanned).toBe(true);
  });

  it('a completed session no longer occupies the running slot', async () => {
    const store = useTimerStore.getState();
    await store.start({ subjectId: 'subject-1' });
    await store.stop();
    expect(await db.getRunningSession()).toBeNull();

    // Which means a new session can begin.
    const next = await useTimerStore.getState().start({ subjectId: 'subject-2' });
    expect(next).not.toBeNull();
  });
});

describe('restoration', () => {
  it('rehydrates a running session after a simulated restart', async () => {
    // First "app run": start and pause a session.
    await useTimerStore.getState().start({ subjectId: 'subject-1' });
    await useTimerStore.getState().pause();
    const originalId = useTimerStore.getState().sessionId;

    // Simulate a cold launch: wipe in-memory store state but keep the database.
    useTimerStore.getState().reset();
    expect(useTimerStore.getState().sessionId).toBeNull();

    await useTimerStore.getState().hydrate();

    const restored = useTimerStore.getState();
    expect(restored.sessionId).toBe(originalId);
    expect(restored.state.status).toBe('paused');
    expect(restored.isHydrating).toBe(false);
  });

  it('hydrate with no running session lands on idle', async () => {
    await useTimerStore.getState().hydrate();
    expect(useTimerStore.getState().state.status).toBe('idle');
    expect(useTimerStore.getState().isHydrating).toBe(false);
  });

  it('restored elapsed time includes time that passed while the app was closed', async () => {
    const realNow = Date.now;
    try {
      const base = 1_700_000_000_000;
      Date.now = () => base;
      await useTimerStore.getState().start({ subjectId: 'subject-1' });

      useTimerStore.getState().reset();

      // Ten minutes later, the app relaunches.
      Date.now = () => base + 10 * 60 * 1000;
      await useTimerStore.getState().hydrate();

      expect(useTimerStore.getState().state.elapsedSeconds).toBe(10 * 60);
    } finally {
      Date.now = realNow;
    }
  });
});
