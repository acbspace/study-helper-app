import type {
  AuthResponse,
  AuthTokens,
  CommunityComment,
  CommunityPost,
  CommunityPostDetail,
  DailyPlan,
  Friend,
  FriendRequest,
  FriendRequests,
  Goal,
  GroupDetail,
  GroupInvitation,
  GroupMember,
  GroupSummary,
  GroupVisibility,
  LeaderboardEntry,
  LeagueMission,
  LeagueStanding,
  Me,
  PostReactionEmoji,
  PostTopic,
  PresenceState,
  PublicUser,
  ReactionEmoji,
  RealtimeTicket,
  ScoreBreakdown,
  SeasonHistoryEntry,
  StatisticsSummary,
  StudySession,
  Subject,
  SyncResult,
  SyncSessionPayload,
  Task,
  TaskPriority,
  TaskStatus,
  UserPresence,
  UserProfile,
  UserSearchResult,
  UserSettings,
  WeeklySummary,
  YearlyInsights,
} from '@study-league/shared-types';

import { ApiError } from './errors';

export interface TokenStore {
  getAccessToken(): Promise<string | null>;
  getRefreshToken(): Promise<string | null>;
  setTokens(tokens: AuthTokens): Promise<void>;
  clear(): Promise<void>;
}

export interface ApiClientOptions {
  baseUrl: string;
  tokens: TokenStore;
  /** Opaque per-installation id; the server stores only a salted hash of it. */
  deviceId?: string;
  /** Called when refreshing fails, so the app can route back to sign-in. */
  onAuthFailure?: () => void;
  fetchImpl?: typeof fetch;
  /**
   * How the refresh token is carried.
   *
   * `'body'` (default) suits a native app, which can put the token in the platform
   * keystore. `'cookie'` asks the server to set an httpOnly cookie instead and omit the
   * token from responses — the only way a browser can hold a long-lived credential that
   * injected JavaScript cannot read.
   */
  refreshTransport?: 'body' | 'cookie';
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  /** Skip the bearer token (registration, login, refresh). */
  anonymous?: boolean;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

/**
 * Typed HTTP client for the Study League API.
 *
 * Responsibilities kept here so no screen has to think about them: attaching auth,
 * refreshing an expired access token exactly once per request, mapping error envelopes to
 * `ApiError`, and passing idempotency keys on retry-sensitive writes.
 */
export class ApiClient {
  private readonly baseUrl: string;
  private readonly tokens: TokenStore;
  private readonly deviceId?: string;
  private readonly onAuthFailure?: () => void;
  private readonly fetchImpl: typeof fetch;
  private readonly usesCookieRefresh: boolean;
  /** Shared across concurrent 401s so a burst of requests triggers one refresh. */
  private refreshInFlight: Promise<boolean> | null = null;

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, '');
    this.tokens = options.tokens;
    this.deviceId = options.deviceId;
    this.onAuthFailure = options.onAuthFailure;
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.usesCookieRefresh = options.refreshTransport === 'cookie';
  }

  // ---------------------------------------------------------------- transport

  private buildUrl(path: string, query?: RequestOptions['query']): string {
    const url = `${this.baseUrl}${path}`;
    if (!query) return url;
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) params.append(key, String(value));
    }
    const qs = params.toString();
    return qs ? `${url}?${qs}` : url;
  }

  private async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const response = await this.send(path, options);

    // One retry after a silent refresh; a second 401 means the session is genuinely gone.
    if (response.status === 401 && !options.anonymous) {
      const refreshed = await this.refreshTokens();
      if (!refreshed) {
        await this.tokens.clear();
        this.onAuthFailure?.();
        throw ApiError.fromResponse(401, await this.readBody(response));
      }
      const retry = await this.send(path, options);
      return this.parse<T>(retry);
    }

    return this.parse<T>(response);
  }

  private async send(path: string, options: RequestOptions): Promise<Response> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (this.deviceId) headers['X-Device-Id'] = this.deviceId;
    if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey;
    if (this.usesCookieRefresh) headers['X-Refresh-Transport'] = 'cookie';

    if (!options.anonymous) {
      const token = await this.tokens.getAccessToken();
      if (token) headers.Authorization = `Bearer ${token}`;
    }

    try {
      return await this.fetchImpl(this.buildUrl(path, options.query), {
        method: options.method ?? 'GET',
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: options.signal,
        // Required for the httpOnly refresh cookie to be sent and accepted cross-origin.
        credentials: this.usesCookieRefresh ? 'include' : undefined,
      });
    } catch (cause) {
      // Offline, DNS failure, timeout: surfaced as a retryable ApiError so callers can
      // fall back to cached data or the outbox instead of crashing.
      throw ApiError.network(cause);
    }
  }

  private async readBody(response: Response): Promise<unknown> {
    const text = await response.text();
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      return null;
    }
  }

  private async parse<T>(response: Response): Promise<T> {
    const body = await this.readBody(response);
    if (!response.ok) throw ApiError.fromResponse(response.status, body);
    return body as T;
  }

  private async refreshTokens(): Promise<boolean> {
    if (this.refreshInFlight) return this.refreshInFlight;

    this.refreshInFlight = (async () => {
      const refreshToken = await this.tokens.getRefreshToken();
      // Under the cookie transport the browser holds the token where this code cannot read
      // it, so an empty store is expected rather than a reason to give up.
      if (!refreshToken && !this.usesCookieRefresh) return false;
      try {
        const response = await this.send('/auth/refresh', {
          method: 'POST',
          body: refreshToken ? { refresh_token: refreshToken } : {},
          anonymous: true,
        });
        if (!response.ok) return false;
        const tokens = (await this.readBody(response)) as AuthTokens;
        await this.tokens.setTokens(tokens);
        return true;
      } catch {
        return false;
      } finally {
        this.refreshInFlight = null;
      }
    })();

    return this.refreshInFlight;
  }

  // ---------------------------------------------------------------- auth

  async register(input: {
    email: string;
    password: string;
    username: string;
    display_name?: string;
    timezone?: string;
    study_category?: string;
    daily_goal_minutes?: number;
    weekly_goal_minutes?: number;
  }): Promise<AuthResponse> {
    const result = await this.request<AuthResponse>('/auth/register', {
      method: 'POST',
      body: input,
      anonymous: true,
    });
    await this.tokens.setTokens(result.tokens);
    return result;
  }

  async login(email: string, password: string): Promise<AuthResponse> {
    const result = await this.request<AuthResponse>('/auth/login', {
      method: 'POST',
      body: { email, password },
      anonymous: true,
    });
    await this.tokens.setTokens(result.tokens);
    return result;
  }

  async logout(): Promise<void> {
    const refreshToken = await this.tokens.getRefreshToken();
    // Under the cookie transport there is nothing to send, but the call still has to happen:
    // it is what revokes the token family server-side and clears the cookie.
    if (refreshToken || this.usesCookieRefresh) {
      try {
        await this.request<void>('/auth/logout', {
          method: 'POST',
          body: refreshToken ? { refresh_token: refreshToken } : {},
          anonymous: true,
        });
      } catch {
        // Signing out locally must succeed even if the server call does not.
      }
    }
    await this.tokens.clear();
  }

  /** Change the password. Every other session is revoked, so new tokens come back. */
  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    const tokens = await this.request<AuthTokens>('/auth/change-password', {
      method: 'POST',
      body: { current_password: currentPassword, new_password: newPassword },
    });
    await this.tokens.setTokens(tokens);
  }

  /** Always resolves — the server will not say whether the address has an account. */
  requestPasswordReset(email: string): Promise<{ message: string }> {
    return this.request<{ message: string }>('/auth/forgot-password', {
      method: 'POST',
      body: { email },
      anonymous: true,
    });
  }

  resetPassword(token: string, newPassword: string): Promise<void> {
    return this.request<void>('/auth/reset-password', {
      method: 'POST',
      body: { token, new_password: newPassword },
      anonymous: true,
    });
  }

  /** Soft-delete this account and sign out. Purged for real after the grace period. */
  async deleteAccount(): Promise<void> {
    await this.request<void>('/me', { method: 'DELETE' });
    await this.tokens.clear();
  }

  getMe(): Promise<Me> {
    return this.request<Me>('/me');
  }

  updateProfile(changes: Partial<UserProfile>): Promise<Me> {
    return this.request<Me>('/me', { method: 'PATCH', body: changes });
  }

  /**
   * Patch settings. Passing `expected_version` opts into optimistic concurrency: the server
   * rejects the write with `version_conflict` if another device changed settings first,
   * rather than letting the later writer silently win.
   */
  updateSettings(changes: Partial<UserSettings> & { expected_version?: number }): Promise<Me> {
    return this.request<Me>('/me/settings', { method: 'PATCH', body: changes });
  }

  // ---------------------------------------------------------------- subjects

  listSubjects(includeArchived = false): Promise<Subject[]> {
    return this.request<Subject[]>('/subjects', {
      query: { include_archived: includeArchived },
    });
  }

  createSubject(input: { name: string; color_hex?: string }): Promise<Subject> {
    return this.request<Subject>('/subjects', { method: 'POST', body: input });
  }

  updateSubject(
    subjectId: string,
    changes: { name?: string; color_hex?: string; sort_order?: number; is_archived?: boolean },
  ): Promise<Subject> {
    return this.request<Subject>(`/subjects/${subjectId}`, { method: 'PATCH', body: changes });
  }

  reorderSubjects(subjectIds: string[]): Promise<Subject[]> {
    return this.request<Subject[]>('/subjects/reorder', {
      method: 'POST',
      body: { subject_ids: subjectIds },
    });
  }

  // ---------------------------------------------------------------- sessions

  getActiveSession(): Promise<StudySession | null> {
    return this.request<StudySession | null>('/study-sessions/active');
  }

  startSession(input: {
    subject_id: string;
    session_id?: string;
    focus_mode?: 'stopwatch' | 'pomodoro';
    pomodoro_focus_minutes?: number;
    started_at?: string;
  }): Promise<StudySession> {
    return this.request<StudySession>('/study-sessions/start', { method: 'POST', body: input });
  }

  pauseSession(sessionId: string, occurredAt?: string): Promise<StudySession> {
    return this.request<StudySession>(`/study-sessions/${sessionId}/pause`, {
      method: 'POST',
      body: { occurred_at: occurredAt },
    });
  }

  resumeSession(sessionId: string, occurredAt?: string): Promise<StudySession> {
    return this.request<StudySession>(`/study-sessions/${sessionId}/resume`, {
      method: 'POST',
      body: { occurred_at: occurredAt },
    });
  }

  stopSession(
    sessionId: string,
    input: { occurred_at?: string; note?: string; went_as_planned?: boolean } = {},
  ): Promise<StudySession> {
    return this.request<StudySession>(`/study-sessions/${sessionId}/stop`, {
      method: 'POST',
      body: input,
    });
  }

  addManualSession(input: {
    subject_id: string;
    started_at: string;
    ended_at: string;
    note?: string;
  }): Promise<StudySession> {
    return this.request<StudySession>('/study-sessions/manual', { method: 'POST', body: input });
  }

  /**
   * Upload sessions recorded offline.
   *
   * Safe to retry: the server keys events by `(session_id, sequence)`, so a replayed batch
   * neither duplicates rows nor changes the result.
   */
  syncSessions(
    sessions: SyncSessionPayload[],
    idempotencyKey?: string,
  ): Promise<{ results: SyncResult[] }> {
    return this.request<{ results: SyncResult[] }>('/study-sessions/sync', {
      method: 'POST',
      body: { sessions },
      idempotencyKey,
    });
  }

  // ---------------------------------------------------------------- statistics

  getStatisticsSummary(date?: string): Promise<StatisticsSummary> {
    return this.request<StatisticsSummary>('/statistics/summary', { query: { date } });
  }

  getWeeklyStatistics(date?: string): Promise<WeeklySummary> {
    return this.request<WeeklySummary>('/statistics/weekly', { query: { date } });
  }

  getYearlyInsights(year?: number): Promise<YearlyInsights> {
    return this.request<YearlyInsights>('/statistics/yearly', { query: { year } });
  }

  /** A portable JSON copy of everything the signed-in user created. */
  exportMyData(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>('/me/export');
  }

  // ---------------------------------------------------------------- planner

  getTodayPlan(): Promise<DailyPlan> {
    return this.request<DailyPlan>('/plans/today');
  }

  getPlan(date: string): Promise<DailyPlan> {
    return this.request<DailyPlan>(`/plans/${date}`);
  }

  createTask(
    date: string,
    input: {
      title: string;
      task_id?: string;
      subject_id?: string | null;
      estimated_minutes?: number;
      priority?: TaskPriority;
    },
  ): Promise<Task> {
    return this.request<Task>(`/plans/${date}/tasks`, { method: 'POST', body: input });
  }

  updateTask(
    taskId: string,
    changes: {
      title?: string;
      subject_id?: string | null;
      estimated_minutes?: number;
      priority?: TaskPriority;
      status?: TaskStatus;
      sort_order?: number;
    },
  ): Promise<Task> {
    return this.request<Task>(`/tasks/${taskId}`, { method: 'PATCH', body: changes });
  }

  deleteTask(taskId: string): Promise<void> {
    return this.request<void>(`/tasks/${taskId}`, { method: 'DELETE' });
  }

  setReflection(date: string, reflection: string | null): Promise<DailyPlan> {
    return this.request<DailyPlan>(`/plans/${date}/reflection`, {
      method: 'PUT',
      body: { reflection },
    });
  }

  carryForward(fromDate: string, toDate: string): Promise<Task[]> {
    return this.request<Task[]>(`/plans/${fromDate}/carry-forward`, {
      method: 'POST',
      body: { to_date: toDate },
    });
  }

  // ---------------------------------------------------------------- friends

  listFriends(): Promise<Friend[]> {
    return this.request<Friend[]>('/friends');
  }

  listFriendRequests(): Promise<FriendRequests> {
    return this.request<FriendRequests>('/friends/requests');
  }

  /** Address a request by user id or username — exactly one. */
  sendFriendRequest(target: { user_id: string } | { username: string }): Promise<FriendRequest> {
    return this.request<FriendRequest>('/friends/requests', { method: 'POST', body: target });
  }

  acceptFriendRequest(friendshipId: string): Promise<Friend> {
    return this.request<Friend>(`/friends/requests/${friendshipId}/accept`, { method: 'POST' });
  }

  declineFriendRequest(friendshipId: string): Promise<void> {
    return this.request<void>(`/friends/requests/${friendshipId}/decline`, { method: 'POST' });
  }

  /** Cancel an outgoing request or remove an existing friend. */
  removeFriendship(friendshipId: string): Promise<void> {
    return this.request<void>(`/friends/${friendshipId}`, { method: 'DELETE' });
  }

  listBlockedUsers(): Promise<PublicUser[]> {
    return this.request<PublicUser[]>('/friends/blocked');
  }

  blockUser(userId: string): Promise<void> {
    return this.request<void>('/friends/blocks', { method: 'POST', body: { user_id: userId } });
  }

  unblockUser(userId: string): Promise<void> {
    return this.request<void>(`/friends/blocks/${userId}`, { method: 'DELETE' });
  }

  searchUsers(query: string, limit?: number): Promise<UserSearchResult[]> {
    return this.request<UserSearchResult[]>('/users/search', { query: { q: query, limit } });
  }

  // ---------------------------------------------------------------- groups

  createGroup(input: {
    name: string;
    description?: string | null;
    rules?: string | null;
    visibility?: GroupVisibility;
    max_members?: number;
  }): Promise<GroupDetail> {
    return this.request<GroupDetail>('/groups', { method: 'POST', body: input });
  }

  listMyGroups(): Promise<GroupSummary[]> {
    return this.request<GroupSummary[]>('/groups/mine');
  }

  discoverGroups(query?: string, limit?: number): Promise<GroupSummary[]> {
    return this.request<GroupSummary[]>('/groups/discover', { query: { q: query, limit } });
  }

  getGroup(groupId: string): Promise<GroupDetail> {
    return this.request<GroupDetail>(`/groups/${groupId}`);
  }

  updateGroup(
    groupId: string,
    changes: {
      name?: string;
      description?: string | null;
      rules?: string | null;
      visibility?: GroupVisibility;
      max_members?: number;
    },
  ): Promise<GroupDetail> {
    return this.request<GroupDetail>(`/groups/${groupId}`, { method: 'PATCH', body: changes });
  }

  deleteGroup(groupId: string): Promise<void> {
    return this.request<void>(`/groups/${groupId}`, { method: 'DELETE' });
  }

  joinGroup(groupId: string): Promise<GroupDetail> {
    return this.request<GroupDetail>(`/groups/${groupId}/join`, { method: 'POST' });
  }

  joinGroupByCode(inviteCode: string): Promise<GroupDetail> {
    return this.request<GroupDetail>('/groups/join', {
      method: 'POST',
      body: { invite_code: inviteCode },
    });
  }

  leaveGroup(groupId: string): Promise<void> {
    return this.request<void>(`/groups/${groupId}/leave`, { method: 'POST' });
  }

  regenerateInviteCode(groupId: string): Promise<GroupDetail> {
    return this.request<GroupDetail>(`/groups/${groupId}/invite-code/regenerate`, {
      method: 'POST',
    });
  }

  setMemberRole(
    groupId: string,
    memberId: string,
    role: 'moderator' | 'member',
  ): Promise<GroupMember> {
    return this.request<GroupMember>(`/groups/${groupId}/members/${memberId}`, {
      method: 'PATCH',
      body: { role },
    });
  }

  removeGroupMember(groupId: string, memberId: string): Promise<void> {
    return this.request<void>(`/groups/${groupId}/members/${memberId}`, { method: 'DELETE' });
  }

  inviteToGroup(groupId: string, userId: string): Promise<GroupInvitation> {
    return this.request<GroupInvitation>(`/groups/${groupId}/invitations`, {
      method: 'POST',
      body: { user_id: userId },
    });
  }

  listGroupInvitations(): Promise<GroupInvitation[]> {
    return this.request<GroupInvitation[]>('/groups/invitations');
  }

  acceptGroupInvitation(invitationId: string): Promise<GroupDetail> {
    return this.request<GroupDetail>(`/groups/invitations/${invitationId}/accept`, {
      method: 'POST',
    });
  }

  declineGroupInvitation(invitationId: string): Promise<void> {
    return this.request<void>(`/groups/invitations/${invitationId}/decline`, { method: 'POST' });
  }

  // ---------------------------------------------------------------- presence

  /** Report my live study state. TTL'd server-side; call every ~30s while active. */
  sendHeartbeat(input: {
    state: PresenceState;
    subject_id?: string | null;
    started_at?: string | null;
  }): Promise<void> {
    return this.request<void>('/presence/heartbeat', { method: 'PUT', body: input });
  }

  goOffline(): Promise<void> {
    return this.request<void>('/presence', { method: 'DELETE' });
  }

  getFriendsPresence(): Promise<UserPresence[]> {
    return this.request<UserPresence[]>('/presence/friends');
  }

  getGroupPresence(groupId: string): Promise<UserPresence[]> {
    return this.request<UserPresence[]>(`/presence/groups/${groupId}`);
  }

  // ---------------------------------------------------------------- realtime

  /** Mint the short-lived ticket used to open the realtime socket. */
  createRealtimeTicket(): Promise<RealtimeTicket> {
    return this.request<RealtimeTicket>('/realtime/ticket', { method: 'POST' });
  }

  /** Send an encouragement to a friend. Delivered live, and recorded for league scoring. */
  sendReaction(targetId: string, emoji: ReactionEmoji): Promise<void> {
    return this.request<void>('/realtime/reactions', {
      method: 'POST',
      body: { target_id: targetId, emoji },
    });
  }

  // ---------------------------------------------------------------- league

  enrollInLeague(): Promise<LeagueStanding> {
    return this.request<LeagueStanding>('/league/enroll', { method: 'POST' });
  }

  getLeagueStanding(): Promise<LeagueStanding> {
    return this.request<LeagueStanding>('/league/current');
  }

  getLeagueLeaderboard(): Promise<LeaderboardEntry[]> {
    return this.request<LeaderboardEntry[]>('/league/leaderboard');
  }

  /** Omit the week to get the week currently in progress. */
  getLeagueBreakdown(weekIndex?: number): Promise<ScoreBreakdown> {
    return this.request<ScoreBreakdown>('/league/breakdown', {
      query: { week_index: weekIndex },
    });
  }

  getLeagueMissions(): Promise<LeagueMission[]> {
    return this.request<LeagueMission[]>('/league/missions');
  }

  getLeagueHistory(): Promise<SeasonHistoryEntry[]> {
    return this.request<SeasonHistoryEntry[]>('/league/history');
  }

  // ---------------------------------------------------------------- goals

  listGoals(includeFinished = false): Promise<Goal[]> {
    return this.request<Goal[]>('/goals', { query: { include_finished: includeFinished } });
  }

  createGoal(input: {
    title: string;
    target_date?: string | null;
    target_weekly_minutes?: number;
    subject_ids?: string[];
    milestones?: { title: string; target_date?: string | null; done?: boolean }[];
    description?: string | null;
  }): Promise<Goal> {
    return this.request<Goal>('/goals', { method: 'POST', body: input });
  }

  updateGoal(
    goalId: string,
    changes: {
      title?: string;
      target_date?: string | null;
      clear_target_date?: boolean;
      target_weekly_minutes?: number;
      status?: 'active' | 'completed' | 'archived';
    },
  ): Promise<Goal> {
    return this.request<Goal>(`/goals/${goalId}`, { method: 'PATCH', body: changes });
  }

  deleteGoal(goalId: string): Promise<void> {
    return this.request<void>(`/goals/${goalId}`, { method: 'DELETE' });
  }

  // ---------------------------------------------------------------- community

  listPosts(topic?: PostTopic): Promise<CommunityPost[]> {
    return this.request<CommunityPost[]>('/community/posts', { query: { topic } });
  }

  createPost(input: { topic?: PostTopic; title: string; body: string }): Promise<CommunityPost> {
    return this.request<CommunityPost>('/community/posts', { method: 'POST', body: input });
  }

  getPost(postId: string): Promise<CommunityPostDetail> {
    return this.request<CommunityPostDetail>(`/community/posts/${postId}`);
  }

  deletePost(postId: string): Promise<void> {
    return this.request<void>(`/community/posts/${postId}`, { method: 'DELETE' });
  }

  addComment(postId: string, body: string): Promise<CommunityComment> {
    return this.request<CommunityComment>(`/community/posts/${postId}/comments`, {
      method: 'POST',
      body: { body },
    });
  }

  reactToPost(postId: string, emoji: PostReactionEmoji): Promise<void> {
    return this.request<void>(`/community/posts/${postId}/reaction`, {
      method: 'PUT',
      body: { emoji },
    });
  }

  unreactToPost(postId: string): Promise<void> {
    return this.request<void>(`/community/posts/${postId}/reaction`, { method: 'DELETE' });
  }

  bookmarkPost(postId: string): Promise<void> {
    return this.request<void>(`/community/posts/${postId}/bookmark`, { method: 'PUT' });
  }

  unbookmarkPost(postId: string): Promise<void> {
    return this.request<void>(`/community/posts/${postId}/bookmark`, { method: 'DELETE' });
  }

  listBookmarkedPosts(): Promise<CommunityPost[]> {
    return this.request<CommunityPost[]>('/community/bookmarks');
  }
}
