/**
 * Broadcast the signed-in user's live presence from the timer.
 *
 * While a session is running we send a heartbeat (studying / on a break) and refresh it on
 * an interval so the server-side TTL never lapses; when the session ends we go offline once.
 * Everything is best-effort — a failed heartbeat is swallowed, because presence must never
 * interfere with the timer, which is the source of truth and works fully offline.
 */

import { useEffect, useRef } from 'react';

import { useAuth } from '@/features/auth/AuthProvider';
import { useTimerStore } from '@/features/timer/timerStore';

const HEARTBEAT_INTERVAL_MS = 30_000;

export function useStudyPresence(): void {
  const { client, status: authStatus } = useAuth();
  const timerStatus = useTimerStore((slice) => slice.state.status);
  const subjectId = useTimerStore((slice) => slice.subjectId);
  // Only announce "offline" if we had actually been broadcasting presence.
  const wasBroadcasting = useRef(false);

  useEffect(() => {
    if (authStatus !== 'authenticated') return;

    if (timerStatus === 'active' || timerStatus === 'paused') {
      wasBroadcasting.current = true;
      const state = timerStatus === 'active' ? 'studying' : 'break';
      const beat = () => {
        void client.sendHeartbeat({ state, subject_id: subjectId }).catch(() => {});
      };
      beat();
      const interval = setInterval(beat, HEARTBEAT_INTERVAL_MS);
      return () => clearInterval(interval);
    }

    if (wasBroadcasting.current) {
      wasBroadcasting.current = false;
      void client.goOffline().catch(() => {});
    }
    return undefined;
  }, [authStatus, timerStatus, subjectId, client]);
}
