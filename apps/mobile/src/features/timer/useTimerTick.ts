/**
 * Drives the timer display.
 *
 * The interval only asks the store to recompute from persisted timestamps — it never adds
 * a second to a counter. That distinction is why a throttled background timer, a dropped
 * frame, or a suspended JS thread cannot make the displayed time wrong.
 */

import { useEffect } from 'react';
import { AppState } from 'react-native';

import { config } from '@/lib/config';

import { useTimerStore } from './timerStore';

export function useTimerTick(): void {
  const status = useTimerStore((state) => state.state.status);
  const tick = useTimerStore((state) => state.tick);

  useEffect(() => {
    if (status !== 'active') return;

    tick();
    const handle = setInterval(tick, config.timerTickMs);

    // Returning to the foreground: recompute immediately so the display is never stale
    // for up to a tick after a long background period.
    const subscription = AppState.addEventListener('change', (next) => {
      if (next === 'active') tick();
    });

    return () => {
      clearInterval(handle);
      subscription.remove();
    };
  }, [status, tick]);
}
