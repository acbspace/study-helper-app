/**
 * Timer state for the UI.
 *
 * Zustand holds only what the screen renders. It is never the source of truth: every
 * action writes an event to SQLite first, then recomputes state from the persisted events.
 * That ordering is what makes the timer survive a crash between the tap and the render.
 *
 * The ticking interval exists purely to trigger re-renders; it never accumulates time.
 */

import { create } from 'zustand';

import * as db from '@/lib/database';
import { newUuid } from '@/lib/uuid';

import {
  IDLE_STATE,
  type TimerEvent,
  type TimerEventType,
  type TimerState,
  canTransition,
  deriveTimerState,
} from './timeline';

export interface TimerSlice {
  sessionId: string | null;
  subjectId: string | null;
  focusMode: 'stopwatch' | 'pomodoro';
  pomodoroFocusMinutes: number | null;
  events: TimerEvent[];
  state: TimerState;
  /** True until the first hydration attempt finishes, so the UI can show a skeleton. */
  isHydrating: boolean;
  lastError: string | null;

  hydrate: () => Promise<void>;
  start: (input: {
    subjectId: string;
    focusMode?: 'stopwatch' | 'pomodoro';
    pomodoroFocusMinutes?: number | null;
  }) => Promise<string | null>;
  pause: () => Promise<void>;
  resume: () => Promise<void>;
  stop: (input?: { note?: string | null; wentAsPlanned?: boolean | null }) => Promise<void>;
  /** Recompute elapsed time against the current clock (called by the display tick). */
  tick: () => void;
  reset: () => void;
}

const initialState = {
  sessionId: null,
  subjectId: null,
  focusMode: 'stopwatch' as const,
  pomodoroFocusMinutes: null,
  events: [] as TimerEvent[],
  state: IDLE_STATE,
  isHydrating: true,
  lastError: null,
};

export const useTimerStore = create<TimerSlice>((set, get) => ({
  ...initialState,

  /**
   * Restore a session after app launch, force-quit, or device restart.
   *
   * Reads the running session (if any) and replays its events; the elapsed time comes out
   * identical to what the user saw before, including time that passed while the app was
   * not running.
   */
  hydrate: async () => {
    try {
      const session = await db.getRunningSession();
      if (!session) {
        set({ ...initialState, isHydrating: false });
        return;
      }
      const events = await db.getEvents(session.id);
      set({
        sessionId: session.id,
        subjectId: session.subjectId,
        focusMode: session.focusMode,
        pomodoroFocusMinutes: session.pomodoroFocusMinutes,
        events,
        state: deriveTimerState(events, Date.now()),
        isHydrating: false,
        lastError: null,
      });
    } catch (error) {
      set({
        ...initialState,
        isHydrating: false,
        lastError: error instanceof Error ? error.message : 'Could not restore your timer.',
      });
    }
  },

  start: async ({ subjectId, focusMode = 'stopwatch', pomodoroFocusMinutes = null }) => {
    const current = get();
    if (current.state.status === 'active' || current.state.status === 'paused') {
      set({ lastError: 'A session is already running.' });
      return null;
    }

    const now = Date.now();
    const sessionId = newUuid();
    const event = {
      id: newUuid(),
      sequence: 1,
      eventType: 'start' as const,
      occurredAt: now,
    };

    try {
      // Persist before touching UI state: a crash here must not lose the session.
      await db.insertSession({
        id: sessionId,
        subjectId,
        focusMode,
        pomodoroFocusMinutes,
        status: 'active',
        startedAt: now,
        endedAt: null,
        note: null,
        wentAsPlanned: null,
        syncState: 'local_only',
        syncMessage: null,
        createdAt: now,
      });
      await db.appendEvent(sessionId, event);
    } catch (error) {
      set({ lastError: error instanceof Error ? error.message : 'Could not start the timer.' });
      return null;
    }

    const events: TimerEvent[] = [
      { sequence: event.sequence, eventType: event.eventType, occurredAt: event.occurredAt },
    ];
    set({
      sessionId,
      subjectId,
      focusMode,
      pomodoroFocusMinutes,
      events,
      state: deriveTimerState(events, now),
      lastError: null,
    });
    return sessionId;
  },

  pause: () => applyTransition(set, get, 'pause'),
  resume: () => applyTransition(set, get, 'resume'),

  stop: async (input = {}) => {
    const { sessionId } = get();
    await applyTransition(set, get, 'stop');
    if (!sessionId) return;
    if (input.note !== undefined || input.wentAsPlanned !== undefined) {
      await db.updateSession(sessionId, {
        note: input.note ?? null,
        wentAsPlanned: input.wentAsPlanned ?? null,
      });
    }
  },

  tick: () => {
    const { events, state } = get();
    // Only a running timer changes with the clock; skip work otherwise.
    if (state.status !== 'active') return;
    set({ state: deriveTimerState(events, Date.now()) });
  },

  reset: () => set({ ...initialState, isHydrating: false }),
}));

async function applyTransition(
  set: (partial: Partial<TimerSlice>) => void,
  get: () => TimerSlice,
  eventType: TimerEventType,
): Promise<void> {
  const { sessionId, state, events } = get();
  if (!sessionId) return;
  if (!canTransition(state.status, eventType)) {
    set({ lastError: `Cannot ${eventType} a ${state.status} session.` });
    return;
  }

  const now = Date.now();
  try {
    const sequence = await db.getNextSequence(sessionId);
    await db.appendEvent(sessionId, {
      id: newUuid(),
      sequence,
      eventType,
      occurredAt: now,
    });

    const nextEvents = [...events, { sequence, eventType, occurredAt: now }];
    const nextState = deriveTimerState(nextEvents, now);

    // A transition applied to a running session can only yield a running or completed
    // state, never idle; narrow explicitly so the persisted status type is honest.
    const persistedStatus: 'active' | 'paused' | 'completed' =
      nextState.status === 'idle' ? 'active' : nextState.status;
    await db.updateSession(sessionId, {
      status: persistedStatus,
      endedAt: nextState.endedAt,
    });

    set({ events: nextEvents, state: nextState, lastError: null });
  } catch (error) {
    set({
      lastError: error instanceof Error ? error.message : `Could not ${eventType} the timer.`,
    });
  }
}
