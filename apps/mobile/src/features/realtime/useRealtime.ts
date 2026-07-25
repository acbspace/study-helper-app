/**
 * Keeps a realtime socket open for the signed-in user and turns events into cache refreshes.
 *
 * Per REALTIME.md the socket only accelerates freshness, so an event never *becomes* state:
 * it invalidates the relevant query and the authoritative, privacy-filtered snapshot is
 * re-fetched over REST. That means a dropped socket degrades to the existing polling
 * interval rather than showing stale or wrong data.
 */

import { useEffect, useMemo, useRef } from 'react';

import type { RealtimeEvent } from '@study-league/api-client';
import { useQueryClient } from '@tanstack/react-query';

import { queryKeys, useMyGroups } from '@/features/api/queries';
import { useAuth } from '@/features/auth/AuthProvider';
import { config } from '@/lib/config';

import { RealtimeClient, type SocketFactory } from './RealtimeClient';

/** http(s)://host/api/v1 → ws(s)://host/api/v1/realtime */
export function realtimeUrl(apiBaseUrl: string): string {
  return `${apiBaseUrl.replace(/^http/, 'ws').replace(/\/$/, '')}/realtime`;
}

const defaultSocketFactory: SocketFactory = (url) =>
  new WebSocket(url) as unknown as ReturnType<SocketFactory>;

export function useRealtime(socketFactory: SocketFactory = defaultSocketFactory): void {
  const { client, status } = useAuth();
  const queryClient = useQueryClient();
  const groups = useMyGroups();
  const clientRef = useRef<RealtimeClient | null>(null);

  // Subscribe to my friend feed plus every group I belong to.
  const channels = useMemo(
    () => ['friends', ...(groups.data ?? []).map((group) => `group:${group.id}`)],
    [groups.data],
  );

  useEffect(() => {
    if (status !== 'authenticated') return;

    const onEvent = (event: RealtimeEvent) => {
      if (event.event === 'presence.changed') {
        void queryClient.invalidateQueries({ queryKey: queryKeys.friendsPresence });
      }
    };

    const realtime = new RealtimeClient({
      url: realtimeUrl(config.apiBaseUrl),
      mintTicket: async () => (await client.createRealtimeTicket()).ticket,
      onEvent,
      socketFactory,
    });
    clientRef.current = realtime;
    void realtime.connect();

    return () => {
      realtime.close();
      clientRef.current = null;
    };
  }, [status, client, queryClient, socketFactory]);

  // Channel membership changes (joining a group) without tearing down the socket.
  useEffect(() => {
    clientRef.current?.setChannels(channels);
  }, [channels]);
}
