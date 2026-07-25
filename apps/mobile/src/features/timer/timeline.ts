/**
 * Client-side timer derivation.
 *
 * This is the mobile mirror of the server's `derive_timeline`, and it exists for one
 * reason: the UI must be able to show correct elapsed time with no network. It is
 * *display* truth only — the server recomputes from the same events and its answer is
 * what counts competitively, so the two can never drift in a way that benefits a user.
 *
 * The critical property: elapsed time is a pure function of (events, now). Nothing
 * accumulates in memory, so backgrounding, force-quitting, or rebooting the phone loses
 * nothing — on relaunch we replay the persisted events and get the same number back.
 */

export type TimerEventType = 'start' | 'pause' | 'resume' | 'stop';
export type TimerStatus = 'idle' | 'active' | 'paused' | 'completed';

export interface TimerEvent {
  sequence: number;
  eventType: TimerEventType;
  /** Epoch milliseconds. */
  occurredAt: number;
}

export interface TimerState {
  status: TimerStatus;
  elapsedSeconds: number;
  startedAt: number | null;
  endedAt: number | null;
  /** Completed [start|resume → pause|stop] intervals. */
  intervalCount: number;
}

const OPENING: ReadonlySet<TimerEventType> = new Set(['start', 'resume']);
const CLOSING: ReadonlySet<TimerEventType> = new Set(['pause', 'stop']);

export const IDLE_STATE: TimerState = {
  status: 'idle',
  elapsedSeconds: 0,
  startedAt: null,
  endedAt: null,
  intervalCount: 0,
};

/**
 * Fold an event stream into timer state.
 *
 * @param events Events for a single session, in any order (sorted internally by sequence).
 * @param now Epoch milliseconds used to measure a still-open interval.
 */
export function deriveTimerState(events: readonly TimerEvent[], now: number): TimerState {
  if (events.length === 0) return IDLE_STATE;

  const ordered = [...events].sort((a, b) => a.sequence - b.sequence);
  const startedAt = ordered[0]!.occurredAt;

  let elapsedMs = 0;
  let intervalCount = 0;
  let openSince: number | null = null;
  let endedAt: number | null = null;
  let stopped = false;
  let previousAt = startedAt;

  for (const event of ordered) {
    // Clamp non-monotonic timestamps (clock changes, DST, tampering) so elapsed time can
    // never run backwards. The server flags these separately.
    const occurredAt = Math.max(event.occurredAt, previousAt);
    previousAt = occurredAt;

    if (stopped) continue;

    if (OPENING.has(event.eventType)) {
      if (openSince === null) openSince = occurredAt;
    } else if (CLOSING.has(event.eventType)) {
      if (openSince !== null) {
        elapsedMs += occurredAt - openSince;
        intervalCount += 1;
        openSince = null;
      }
      if (event.eventType === 'stop') {
        stopped = true;
        endedAt = occurredAt;
      }
    }
  }

  if (stopped) {
    return {
      status: 'completed',
      elapsedSeconds: Math.floor(elapsedMs / 1000),
      startedAt,
      endedAt,
      intervalCount,
    };
  }

  if (openSince !== null) {
    elapsedMs += Math.max(now - openSince, 0);
    return {
      status: 'active',
      elapsedSeconds: Math.floor(elapsedMs / 1000),
      startedAt,
      endedAt: null,
      intervalCount,
    };
  }

  return {
    status: 'paused',
    elapsedSeconds: Math.floor(elapsedMs / 1000),
    startedAt,
    endedAt: null,
    intervalCount,
  };
}

/** Whether a transition is legal, mirroring the server's rules. */
export function canTransition(status: TimerStatus, eventType: TimerEventType): boolean {
  switch (status) {
    case 'idle':
      return eventType === 'start';
    case 'active':
      return eventType === 'pause' || eventType === 'stop';
    case 'paused':
      return eventType === 'resume' || eventType === 'stop';
    case 'completed':
      return false;
  }
}

/** Format seconds as H:MM:SS (or M:SS below an hour) for the timer display. */
export function formatDuration(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = safe % 60;
  const pad = (value: number) => value.toString().padStart(2, '0');
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}

/** Human-readable duration for summaries, e.g. "2h 15m". */
export function formatDurationLong(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  if (hours === 0 && minutes === 0) return '0m';
  if (hours === 0) return `${minutes}m`;
  if (minutes === 0) return `${hours}h`;
  return `${hours}h ${minutes}m`;
}

/**
 * Screen-reader friendly duration. VoiceOver reading "2:15:00" as a time of day is a
 * common accessibility failure, so announce the units explicitly.
 */
export function formatDurationAccessible(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = safe % 60;
  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours} hour${hours === 1 ? '' : 's'}`);
  if (minutes > 0) parts.push(`${minutes} minute${minutes === 1 ? '' : 's'}`);
  if (hours === 0 && seconds > 0) parts.push(`${seconds} second${seconds === 1 ? '' : 's'}`);
  return parts.length > 0 ? parts.join(' ') : '0 minutes';
}
