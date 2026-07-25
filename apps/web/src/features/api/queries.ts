/**
 * TanStack Query hooks for the dashboard, all reusing the shared ApiClient.
 *
 * League and presence reads do not retry: "no season" / "not enrolled" are ordinary states
 * the UI renders, not failures worth hammering the API over.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import type {
  LeagueStanding,
  StatisticsSummary,
  Subject,
  UserPresence,
} from '@study-league/api-client';

import { useAuth } from '@/features/auth/AuthProvider';

const OFFLINE_TOLERANT = { staleTime: 30_000, gcTime: 24 * 60 * 60 * 1000, retry: 2 } as const;
const NO_RETRY = { staleTime: 60_000, retry: false } as const;

export function useStatisticsSummary(): UseQueryResult<StatisticsSummary> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: ['statistics', 'summary'],
    queryFn: () => client.getStatisticsSummary(),
    enabled: status === 'authenticated',
    ...OFFLINE_TOLERANT,
  });
}

export function useSubjects(): UseQueryResult<Subject[]> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: ['subjects'],
    queryFn: () => client.listSubjects(),
    enabled: status === 'authenticated',
    ...OFFLINE_TOLERANT,
  });
}

export function useLeagueStanding(): UseQueryResult<LeagueStanding> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: ['league', 'current'],
    queryFn: () => client.getLeagueStanding(),
    enabled: status === 'authenticated',
    ...NO_RETRY,
  });
}

export function useFriendsPresence(): UseQueryResult<UserPresence[]> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: ['presence', 'friends'],
    queryFn: () => client.getFriendsPresence(),
    enabled: status === 'authenticated',
    staleTime: 15_000,
    refetchInterval: 30_000,
    retry: 1,
  });
}
