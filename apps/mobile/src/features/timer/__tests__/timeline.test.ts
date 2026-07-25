/**
 * Client timeline derivation — the display mirror of the server's algorithm.
 *
 * These must agree with the backend's `test_timeline.py`: if the two ever diverge, a user
 * would see one number and be scored on another.
 */

import {
  type TimerEvent,
  canTransition,
  deriveTimerState,
  formatDuration,
  formatDurationAccessible,
  formatDurationLong,
} from '../timeline';

const START = 1_700_000_000_000; // fixed epoch ms
const minutes = (n: number) => n * 60 * 1000;

function event(sequence: number, type: TimerEvent['eventType'], offsetMin: number): TimerEvent {
  return { sequence, eventType: type, occurredAt: START + minutes(offsetMin) };
}

describe('deriveTimerState', () => {
  it('returns idle for no events', () => {
    expect(deriveTimerState([], START).status).toBe('idle');
  });

  it('counts a running session up to now', () => {
    const state = deriveTimerState([event(1, 'start', 0)], START + minutes(30));
    expect(state.status).toBe('active');
    expect(state.elapsedSeconds).toBe(30 * 60);
  });

  it('freezes elapsed time while paused', () => {
    const events = [event(1, 'start', 0), event(2, 'pause', 25)];
    // An hour passes while paused; elapsed must not move.
    const state = deriveTimerState(events, START + minutes(85));
    expect(state.status).toBe('paused');
    expect(state.elapsedSeconds).toBe(25 * 60);
  });

  it('resumes the clock after a pause', () => {
    const events = [event(1, 'start', 0), event(2, 'pause', 25), event(3, 'resume', 40)];
    const state = deriveTimerState(events, START + minutes(50));
    expect(state.elapsedSeconds).toBe(35 * 60); // 25 + 10
  });

  it('finalises duration on stop and ignores now', () => {
    const events = [
      event(1, 'start', 0),
      event(2, 'pause', 25),
      event(3, 'resume', 40),
      event(4, 'stop', 60),
    ];
    const state = deriveTimerState(events, START + minutes(9999));
    expect(state.status).toBe('completed');
    expect(state.elapsedSeconds).toBe(45 * 60);
    expect(state.intervalCount).toBe(2);
  });

  it('orders by sequence, not arrival order (offline sync delivers out of order)', () => {
    const events = [
      event(4, 'stop', 60),
      event(1, 'start', 0),
      event(3, 'resume', 40),
      event(2, 'pause', 25),
    ];
    expect(deriveTimerState(events, START + minutes(500)).elapsedSeconds).toBe(45 * 60);
  });

  it('clamps non-monotonic timestamps so elapsed never goes negative', () => {
    const events = [event(1, 'start', 0), event(2, 'stop', -10)];
    expect(deriveTimerState(events, START).elapsedSeconds).toBe(0);
  });

  it('survives a simulated restart: same events, same elapsed', () => {
    const events = [event(1, 'start', 0), event(2, 'pause', 20)];
    // "Before" the app was killed and "after" relaunch: identical inputs, identical output.
    const before = deriveTimerState(events, START + minutes(20));
    const after = deriveTimerState(events, START + minutes(999));
    expect(after.elapsedSeconds).toBe(before.elapsedSeconds);
    expect(after.status).toBe('paused');
  });
});

describe('canTransition', () => {
  it('allows legal transitions', () => {
    expect(canTransition('idle', 'start')).toBe(true);
    expect(canTransition('active', 'pause')).toBe(true);
    expect(canTransition('active', 'stop')).toBe(true);
    expect(canTransition('paused', 'resume')).toBe(true);
  });

  it('rejects illegal transitions', () => {
    expect(canTransition('active', 'resume')).toBe(false);
    expect(canTransition('paused', 'pause')).toBe(false);
    expect(canTransition('completed', 'resume')).toBe(false);
    expect(canTransition('idle', 'pause')).toBe(false);
  });
});

describe('formatting', () => {
  it('formats below and above an hour', () => {
    expect(formatDuration(0)).toBe('0:00');
    expect(formatDuration(65)).toBe('1:05');
    expect(formatDuration(3661)).toBe('1:01:01');
  });

  it('formats human-readable durations', () => {
    expect(formatDurationLong(0)).toBe('0m');
    expect(formatDurationLong(45 * 60)).toBe('45m');
    expect(formatDurationLong(2 * 3600 + 15 * 60)).toBe('2h 15m');
    expect(formatDurationLong(3600)).toBe('1h');
  });

  it('announces durations with explicit units for screen readers', () => {
    expect(formatDurationAccessible(0)).toBe('0 minutes');
    expect(formatDurationAccessible(3661)).toBe('1 hour 1 minute');
    expect(formatDurationAccessible(45)).toBe('45 seconds');
  });
});
