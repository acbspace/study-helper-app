/**
 * TanStack Query hooks.
 *
 * Server state lives here; nothing else caches API responses. Queries are configured to
 * keep showing the last good data while offline rather than flipping to an error, because
 * a student on a subway should still see today's totals.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';

import type {
  AppNotification,
  CommunityPost,
  DailyPlan,
  Friend,
  FriendRequests,
  Goal,
  GroupInvitation,
  GroupSummary,
  LeaderboardEntry,
  LeagueMission,
  LeagueStanding,
  PostReactionEmoji,
  PostTopic,
  PublicUser,
  ReportSubjectType,
  ScoreBreakdown,
  StatisticsSummary,
  Subject,
  Task,
  TaskPriority,
  TaskStatus,
  UnreadCount,
  UserPresence,
  UserProfile,
  UserSearchResult,
  UserSettings,
  YearlyInsights,
} from '@study-league/api-client';

import { useAuth } from '@/features/auth/AuthProvider';

export const queryKeys = {
  me: ['me'] as const,
  subjects: ['subjects'] as const,
  statisticsSummary: (date?: string) => ['statistics', 'summary', date ?? 'today'] as const,
  weeklyStatistics: (date?: string) => ['statistics', 'weekly', date ?? 'current'] as const,
  todayPlan: ['plans', 'today'] as const,
  plan: (date: string) => ['plans', date] as const,
  friends: ['friends'] as const,
  friendRequests: ['friends', 'requests'] as const,
  userSearch: (query: string) => ['users', 'search', query] as const,
  myGroups: ['groups', 'mine'] as const,
  groupInvitations: ['groups', 'invitations'] as const,
  groupDiscover: (query: string) => ['groups', 'discover', query] as const,
  friendsPresence: ['presence', 'friends'] as const,
  leagueStanding: ['league', 'current'] as const,
  leagueLeaderboard: ['league', 'leaderboard'] as const,
  leagueBreakdown: ['league', 'breakdown'] as const,
  leagueMissions: ['league', 'missions'] as const,
  goals: ['goals'] as const,
  blockedUsers: ['users', 'blocked'] as const,
  notifications: ['notifications'] as const,
  unreadCount: ['notifications', 'unread-count'] as const,
  yearlyInsights: (year?: number) => ['statistics', 'yearly', year ?? 'current'] as const,
  posts: (topic?: string) => ['community', 'posts', topic ?? 'all'] as const,
  postDetail: (id: string) => ['community', 'post', id] as const,
};

/** Cached data stays useful for a while: offline is a normal state for this product. */
const OFFLINE_TOLERANT = {
  staleTime: 30_000,
  gcTime: 24 * 60 * 60 * 1000,
  retry: 2,
} as const;

export function useSubjects(): UseQueryResult<Subject[]> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.subjects,
    queryFn: () => client.listSubjects(),
    enabled: status === 'authenticated',
    ...OFFLINE_TOLERANT,
  });
}

export function useStatisticsSummary(date?: string): UseQueryResult<StatisticsSummary> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.statisticsSummary(date),
    queryFn: () => client.getStatisticsSummary(date),
    enabled: status === 'authenticated',
    ...OFFLINE_TOLERANT,
  });
}

export function useTodayPlan(): UseQueryResult<DailyPlan> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.todayPlan,
    queryFn: () => client.getTodayPlan(),
    enabled: status === 'authenticated',
    ...OFFLINE_TOLERANT,
  });
}

export function useCreateSubject() {
  const { client } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; color_hex?: string }) => client.createSubject(input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.subjects });
    },
  });
}

export function useUpdateSubject() {
  const { client } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      subjectId,
      changes,
    }: {
      subjectId: string;
      changes: { name?: string; color_hex?: string; is_archived?: boolean; sort_order?: number };
    }) => client.updateSubject(subjectId, changes),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.subjects });
    },
  });
}

export function useCreateTask(date: string) {
  const { client } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      title: string;
      subject_id?: string | null;
      estimated_minutes?: number;
      priority?: TaskPriority;
    }) => client.createTask(date, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.todayPlan });
      void queryClient.invalidateQueries({ queryKey: ['statistics'] });
    },
  });
}

export function useUpdateTask() {
  const { client } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ taskId, changes }: { taskId: string; changes: { status?: TaskStatus } }) =>
      client.updateTask(taskId, changes),

    // Ticking a task off must feel instant; the list is corrected if the call fails.
    onMutate: async ({ taskId, changes }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.todayPlan });
      const previous = queryClient.getQueryData<DailyPlan>(queryKeys.todayPlan);
      if (previous) {
        queryClient.setQueryData<DailyPlan>(queryKeys.todayPlan, {
          ...previous,
          tasks: previous.tasks.map((task: Task) =>
            task.id === taskId ? { ...task, ...changes } : task,
          ),
        });
      }
      return { previous };
    },

    onError: (_error, _variables, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.todayPlan, context.previous);
      }
    },

    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.todayPlan });
      void queryClient.invalidateQueries({ queryKey: ['statistics'] });
    },
  });
}

// ------------------------------------------------------------------ friends

export function useFriends(): UseQueryResult<Friend[]> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.friends,
    queryFn: () => client.listFriends(),
    enabled: status === 'authenticated',
    ...OFFLINE_TOLERANT,
  });
}

export function useFriendRequests(): UseQueryResult<FriendRequests> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.friendRequests,
    queryFn: () => client.listFriendRequests(),
    enabled: status === 'authenticated',
    ...OFFLINE_TOLERANT,
  });
}

/** Searches once the query has some substance; a blank box shows nothing rather than everyone. */
export function useSearchUsers(query: string): UseQueryResult<UserSearchResult[]> {
  const { client, status } = useAuth();
  const trimmed = query.trim();
  return useQuery({
    queryKey: queryKeys.userSearch(trimmed),
    queryFn: () => client.searchUsers(trimmed),
    enabled: status === 'authenticated' && trimmed.length >= 2,
    staleTime: 15_000,
    retry: 1,
  });
}

/** Everything that changes a relationship also changes search results, so refetch those too. */
function useRelationshipInvalidation() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.friends });
    void queryClient.invalidateQueries({ queryKey: queryKeys.friendRequests });
    void queryClient.invalidateQueries({ queryKey: ['users', 'search'] });
  };
}

export function useSendFriendRequest() {
  const { client } = useAuth();
  const invalidate = useRelationshipInvalidation();
  return useMutation({
    mutationFn: (target: { user_id: string } | { username: string }) =>
      client.sendFriendRequest(target),
    onSuccess: invalidate,
  });
}

export function useAcceptFriendRequest() {
  const { client } = useAuth();
  const invalidate = useRelationshipInvalidation();
  return useMutation({
    mutationFn: (friendshipId: string) => client.acceptFriendRequest(friendshipId),
    onSuccess: invalidate,
  });
}

export function useDeclineFriendRequest() {
  const { client } = useAuth();
  const invalidate = useRelationshipInvalidation();
  return useMutation({
    mutationFn: (friendshipId: string) => client.declineFriendRequest(friendshipId),
    onSuccess: invalidate,
  });
}

export function useRemoveFriendship() {
  const { client } = useAuth();
  const invalidate = useRelationshipInvalidation();
  return useMutation({
    mutationFn: (friendshipId: string) => client.removeFriendship(friendshipId),
    onSuccess: invalidate,
  });
}

export function useBlockUser() {
  const { client } = useAuth();
  const invalidate = useRelationshipInvalidation();
  return useMutation({
    mutationFn: (userId: string) => client.blockUser(userId),
    onSuccess: invalidate,
  });
}

// ------------------------------------------------------------------ groups

export function useMyGroups(): UseQueryResult<GroupSummary[]> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.myGroups,
    queryFn: () => client.listMyGroups(),
    enabled: status === 'authenticated',
    ...OFFLINE_TOLERANT,
  });
}

export function useGroupInvitations(): UseQueryResult<GroupInvitation[]> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.groupInvitations,
    queryFn: () => client.listGroupInvitations(),
    enabled: status === 'authenticated',
    ...OFFLINE_TOLERANT,
  });
}

export function useDiscoverGroups(query: string): UseQueryResult<GroupSummary[]> {
  const { client, status } = useAuth();
  const trimmed = query.trim();
  return useQuery({
    queryKey: queryKeys.groupDiscover(trimmed),
    queryFn: () => client.discoverGroups(trimmed),
    enabled: status === 'authenticated' && trimmed.length >= 2,
    staleTime: 15_000,
    retry: 1,
  });
}

/** Anything that changes group membership can change all three group views. */
function useGroupInvalidation() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.myGroups });
    void queryClient.invalidateQueries({ queryKey: queryKeys.groupInvitations });
    void queryClient.invalidateQueries({ queryKey: ['groups', 'discover'] });
  };
}

export function useCreateGroup() {
  const { client } = useAuth();
  const invalidate = useGroupInvalidation();
  return useMutation({
    mutationFn: (input: {
      name: string;
      description?: string | null;
      visibility?: 'public' | 'private' | 'invite';
      max_members?: number;
    }) => client.createGroup(input),
    onSuccess: invalidate,
  });
}

export function useJoinGroup() {
  const { client } = useAuth();
  const invalidate = useGroupInvalidation();
  return useMutation({
    mutationFn: (groupId: string) => client.joinGroup(groupId),
    onSuccess: invalidate,
  });
}

export function useJoinGroupByCode() {
  const { client } = useAuth();
  const invalidate = useGroupInvalidation();
  return useMutation({
    mutationFn: (inviteCode: string) => client.joinGroupByCode(inviteCode),
    onSuccess: invalidate,
  });
}

export function useLeaveGroup() {
  const { client } = useAuth();
  const invalidate = useGroupInvalidation();
  return useMutation({
    mutationFn: (groupId: string) => client.leaveGroup(groupId),
    onSuccess: invalidate,
  });
}

export function useAcceptGroupInvitation() {
  const { client } = useAuth();
  const invalidate = useGroupInvalidation();
  return useMutation({
    mutationFn: (invitationId: string) => client.acceptGroupInvitation(invitationId),
    onSuccess: invalidate,
  });
}

export function useDeclineGroupInvitation() {
  const { client } = useAuth();
  const invalidate = useGroupInvalidation();
  return useMutation({
    mutationFn: (invitationId: string) => client.declineGroupInvitation(invitationId),
    onSuccess: invalidate,
  });
}

// ------------------------------------------------------------------ presence

// ------------------------------------------------------------------ league

/**
 * League reads deliberately do not retry: "no season running" and "not enrolled yet" are
 * ordinary 404s the screen renders as states, not failures worth hammering the API over.
 */
const LEAGUE_QUERY = { staleTime: 60_000, retry: false } as const;

export function useLeagueStanding(): UseQueryResult<LeagueStanding> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.leagueStanding,
    queryFn: () => client.getLeagueStanding(),
    enabled: status === 'authenticated',
    ...LEAGUE_QUERY,
  });
}

export function useLeagueLeaderboard(enabled = true): UseQueryResult<LeaderboardEntry[]> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.leagueLeaderboard,
    queryFn: () => client.getLeagueLeaderboard(),
    enabled: status === 'authenticated' && enabled,
    ...LEAGUE_QUERY,
  });
}

export function useLeagueBreakdown(enabled = true): UseQueryResult<ScoreBreakdown> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.leagueBreakdown,
    queryFn: () => client.getLeagueBreakdown(),
    enabled: status === 'authenticated' && enabled,
    ...LEAGUE_QUERY,
  });
}

export function useLeagueMissions(enabled = true): UseQueryResult<LeagueMission[]> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.leagueMissions,
    queryFn: () => client.getLeagueMissions(),
    enabled: status === 'authenticated' && enabled,
    ...LEAGUE_QUERY,
  });
}

export function useEnrollInLeague() {
  const { client } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => client.enrollInLeague(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['league'] });
    },
  });
}

// ------------------------------------------------------------------ goals

export function useGoals(includeFinished = false): UseQueryResult<Goal[]> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: [...queryKeys.goals, includeFinished],
    queryFn: () => client.listGoals(includeFinished),
    enabled: status === 'authenticated',
    ...OFFLINE_TOLERANT,
  });
}

export function useCreateGoal() {
  const { client } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      title: string;
      target_date?: string | null;
      target_weekly_minutes?: number;
    }) => client.createGoal(input),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.goals }),
  });
}

export function useUpdateGoal() {
  const { client } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      goalId,
      changes,
    }: {
      goalId: string;
      changes: { status?: 'active' | 'completed' | 'archived'; title?: string };
    }) => client.updateGoal(goalId, changes),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.goals }),
  });
}

export function useDeleteGoal() {
  const { client } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (goalId: string) => client.deleteGoal(goalId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.goals }),
  });
}

// ------------------------------------------------------------------ yearly insights

export function useYearlyInsights(year?: number): UseQueryResult<YearlyInsights> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.yearlyInsights(year),
    queryFn: () => client.getYearlyInsights(year),
    enabled: status === 'authenticated',
    ...OFFLINE_TOLERANT,
  });
}

// ------------------------------------------------------------------ community

export function usePosts(topic?: PostTopic): UseQueryResult<CommunityPost[]> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.posts(topic),
    queryFn: () => client.listPosts(topic),
    enabled: status === 'authenticated',
    ...OFFLINE_TOLERANT,
  });
}

export function useCreatePost() {
  const { client } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { topic?: PostTopic; title: string; body: string }) =>
      client.createPost(input),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['community', 'posts'] }),
  });
}

/** React and bookmark toggles just need the feed to refresh afterwards. */
function useCommunityRefresh() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: ['community'] });
}

export function useReactToPost() {
  const { client } = useAuth();
  const refresh = useCommunityRefresh();
  return useMutation({
    mutationFn: ({ postId, emoji }: { postId: string; emoji: PostReactionEmoji }) =>
      client.reactToPost(postId, emoji),
    onSuccess: refresh,
  });
}

export function useToggleBookmark() {
  const { client } = useAuth();
  const refresh = useCommunityRefresh();
  return useMutation({
    mutationFn: ({ postId, bookmarked }: { postId: string; bookmarked: boolean }) =>
      bookmarked ? client.unbookmarkPost(postId) : client.bookmarkPost(postId),
    onSuccess: refresh,
  });
}

/** Which friends are studying right now. Polls so the list stays live without a socket. */
export function useFriendsPresence(): UseQueryResult<UserPresence[]> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.friendsPresence,
    queryFn: () => client.getFriendsPresence(),
    enabled: status === 'authenticated',
    staleTime: 15_000,
    refetchInterval: 30_000,
    retry: 1,
  });
}

// ------------------------------------------------------------------ profile & settings

export function useUpdateProfile() {
  const { client, refreshUser } = useAuth();
  return useMutation({
    mutationFn: (changes: Partial<UserProfile>) => client.updateProfile(changes),
    // `Me` lives in the auth context rather than the query cache, so it is the thing to
    // refresh — there is no second copy to invalidate.
    onSuccess: () => refreshUser(),
  });
}

export function useUpdateSettings() {
  const { client, refreshUser } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: Partial<UserSettings> & { expected_version?: number }) =>
      client.updateSettings(changes),
    onSuccess: async () => {
      await refreshUser();
      // Scheduled days and goals are inputs to both, so cached figures computed under the
      // old settings are now wrong rather than merely stale.
      void queryClient.invalidateQueries({ queryKey: ['statistics'] });
      void queryClient.invalidateQueries({ queryKey: ['league'] });
    },
  });
}

export function useBlockedUsers(): UseQueryResult<PublicUser[]> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.blockedUsers,
    queryFn: () => client.listBlockedUsers(),
    enabled: status === 'authenticated',
    ...OFFLINE_TOLERANT,
  });
}

// ------------------------------------------------------------------ notifications

export function useNotifications(): UseQueryResult<AppNotification[]> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.notifications,
    queryFn: () => client.listNotifications({ limit: 50 }),
    enabled: status === 'authenticated',
    ...OFFLINE_TOLERANT,
  });
}

/** Drives the tab-bar badge, so it polls rather than waiting for a screen visit. */
export function useUnreadNotificationCount(): UseQueryResult<UnreadCount> {
  const { client, status } = useAuth();
  return useQuery({
    queryKey: queryKeys.unreadCount,
    queryFn: () => client.getUnreadNotificationCount(),
    enabled: status === 'authenticated',
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: 1,
  });
}

function useNotificationRefresh() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.notifications });
    void queryClient.invalidateQueries({ queryKey: queryKeys.unreadCount });
  };
}

export function useMarkNotificationRead() {
  const { client } = useAuth();
  const refresh = useNotificationRefresh();
  return useMutation({
    mutationFn: (notificationId: string) => client.markNotificationRead(notificationId),
    onSuccess: refresh,
  });
}

export function useMarkAllNotificationsRead() {
  const { client } = useAuth();
  const refresh = useNotificationRefresh();
  return useMutation({
    mutationFn: () => client.markAllNotificationsRead(),
    onSuccess: refresh,
  });
}

// ------------------------------------------------------------------ reporting

export function useReportContent() {
  const { client } = useAuth();
  return useMutation({
    mutationFn: (input: { subject_type: ReportSubjectType; subject_id: string; reason: string }) =>
      client.reportContent(input),
  });
}

export function useUnblockUser() {
  const { client } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => client.unblockUser(userId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.blockedUsers });
      // Unblocking makes the other person visible again across every social read.
      void queryClient.invalidateQueries({ queryKey: queryKeys.friends });
      void queryClient.invalidateQueries({ queryKey: queryKeys.friendsPresence });
    },
  });
}
