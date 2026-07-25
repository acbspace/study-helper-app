/**
 * Drives the outbox.
 *
 * Flushes when the app returns to the foreground and on a slow timer while anything is
 * pending. Failures are silent by design: being offline is the expected state this whole
 * mechanism exists for, so it must not produce error noise.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, type AppStateStatus } from 'react-native';

import { useQueryClient } from '@tanstack/react-query';

import { useAuth } from '@/features/auth/AuthProvider';
import { config } from '@/lib/config';

import { flushOutbox, pendingCount } from './outbox';

export interface SyncStatus {
  pending: number;
  isSyncing: boolean;
  lastSyncedAt: number | null;
  /** Server explanations for excluded sessions, surfaced to the user after a flush. */
  messages: string[];
  syncNow: () => Promise<void>;
  dismissMessages: () => void;
}

export function useSync(): SyncStatus {
  const { client, status } = useAuth();
  const queryClient = useQueryClient();

  const [pending, setPending] = useState(0);
  const [isSyncing, setIsSyncing] = useState(false);
  const [lastSyncedAt, setLastSyncedAt] = useState<number | null>(null);
  const [messages, setMessages] = useState<string[]>([]);
  // Guards against a foreground event and the interval firing at the same moment.
  const inFlight = useRef(false);

  const refreshPending = useCallback(async () => {
    try {
      setPending(await pendingCount());
    } catch {
      // A local database read failure should not break the screen.
    }
  }, []);

  const syncNow = useCallback(async () => {
    if (status !== 'authenticated' || inFlight.current) return;
    inFlight.current = true;
    setIsSyncing(true);
    try {
      const summary = await flushOutbox(client);
      if (summary.attempted > 0) {
        setLastSyncedAt(Date.now());
        if (summary.messages.length > 0) setMessages(summary.messages);
        // Totals changed on the server; let the dashboard refetch.
        void queryClient.invalidateQueries({ queryKey: ['statistics'] });
      }
    } catch {
      // Expected while offline. Rows stay queued and the next attempt retries.
    } finally {
      inFlight.current = false;
      setIsSyncing(false);
      await refreshPending();
    }
  }, [client, queryClient, refreshPending, status]);

  useEffect(() => {
    if (status !== 'authenticated') return;
    void syncNow();
  }, [status, syncNow]);

  // Coming back to the app is the most likely moment for connectivity to have returned.
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (next === 'active') void syncNow();
    });
    return () => subscription.remove();
  }, [syncNow]);

  useEffect(() => {
    if (pending === 0 || status !== 'authenticated') return;
    const handle = setInterval(() => void syncNow(), config.syncRetryMs);
    return () => clearInterval(handle);
  }, [pending, status, syncNow]);

  return {
    pending,
    isSyncing,
    lastSyncedAt,
    messages,
    syncNow,
    dismissMessages: () => setMessages([]),
  };
}
