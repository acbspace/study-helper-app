/**
 * Contract types shared between the API and its clients.
 *
 * These mirror the FastAPI Pydantic schemas. `npm run generate:api` regenerates
 * `src/generated/api.d.ts` from the live OpenAPI document; the hand-written types below are
 * the curated surface clients actually import, so a schema change that breaks a client
 * fails at compile time rather than at runtime.
 */

export type SessionSource = 'timer' | 'manual';
export type SessionStatus = 'active' | 'paused' | 'completed' | 'discarded';
export type SessionEventType = 'start' | 'pause' | 'resume' | 'stop';
export type FocusMode = 'stopwatch' | 'pomodoro';
export type IntegrityStatus = 'ok' | 'flagged' | 'excluded';
export type TaskPriority = 'low' | 'normal' | 'high';
export type TaskStatus = 'pending' | 'done' | 'deferred';
export type SyncOutcome = 'accepted' | 'merged' | 'flagged' | 'rejected';

/** The signed-in user's relationship to another user, as reported by search. */
export type RelationshipState =
  'none' | 'friends' | 'request_sent' | 'request_received' | 'blocked';

export type GroupVisibility = 'public' | 'private' | 'invite';
export type GroupRole = 'owner' | 'moderator' | 'member';

/** Live, ephemeral study state. Absence of a presence row means "offline". */
export type PresenceState = 'studying' | 'break' | 'idle';

/** Stable machine-readable error codes. Clients branch on these, never on message text. */
export type ApiErrorCode =
  | 'validation_error'
  | 'not_authenticated'
  | 'token_expired'
  | 'invalid_credentials'
  | 'not_permitted'
  | 'rate_limited'
  | 'email_already_registered'
  | 'username_taken'
  | 'subject_not_found'
  | 'subject_name_taken'
  | 'session_not_found'
  | 'active_session_exists'
  | 'invalid_transition'
  | 'timeline_invalid'
  | 'plan_not_found'
  | 'task_not_found'
  | 'user_not_found'
  | 'friendship_not_found'
  | 'friend_request_exists'
  | 'already_friends'
  | 'cannot_friend_self'
  | 'user_blocked'
  | 'group_not_found'
  | 'not_group_member'
  | 'already_group_member'
  | 'group_full'
  | 'invalid_invite_code'
  | 'invitation_not_found'
  | 'invitation_exists'
  | 'owner_cannot_leave'
  | 'no_active_season'
  | 'not_enrolled'
  | 'score_not_found'
  | 'report_exists'
  | 'cannot_report_self'
  | 'notification_not_found'
  | 'device_required'
  | 'goal_not_found'
  | 'post_not_found'
  | 'comment_not_found'
  | 'version_conflict'
  | 'internal_error';

export interface ApiErrorBody {
  error: {
    code: ApiErrorCode;
    message: string;
    details?: Record<string, unknown>;
  };
}

export interface UserProfile {
  username: string;
  display_name: string;
  avatar_url: string | null;
  country_code: string | null;
  study_category: string;
  bio: string | null;
}

export interface UserSettings {
  timezone: string;
  language: string;
  daily_goal_minutes: number;
  weekly_goal_minutes: number;
  /** Bitmask: Monday = 1 << 0 … Sunday = 1 << 6. */
  scheduled_study_days: number;
  pomodoro_focus_minutes: number;
  pomodoro_break_minutes: number;
  privacy_show_subject: boolean;
  privacy_show_presence: boolean;
  notifications_enabled: boolean;
  version: number;
}

export interface Me {
  id: string;
  email: string;
  profile: UserProfile;
  settings: UserSettings;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface AuthResponse {
  user: Me;
  tokens: AuthTokens;
}

export interface Subject {
  id: string;
  name: string;
  color_hex: string;
  sort_order: number;
  is_archived: boolean;
}

export interface StudySession {
  id: string;
  subject_id: string;
  source: SessionSource;
  status: SessionStatus;
  focus_mode: FocusMode;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number;
  note: string | null;
  went_as_planned: boolean | null;
  integrity_status: IntegrityStatus;
  integrity_reasons: string[];
  synced_at: string | null;
}

export interface SessionEventPayload {
  id: string;
  sequence: number;
  event_type: SessionEventType;
  occurred_at: string;
}

export interface SyncSessionPayload {
  id: string;
  subject_id: string;
  events: SessionEventPayload[];
  source?: SessionSource;
  focus_mode?: FocusMode;
  pomodoro_focus_minutes?: number | null;
  note?: string | null;
  went_as_planned?: boolean | null;
  client_created_at?: string | null;
}

export interface SyncResult {
  session_id: string;
  outcome: SyncOutcome;
  status: SessionStatus;
  duration_seconds: number;
  integrity_status: IntegrityStatus;
  reasons: string[];
  /** Plain-language explanation shown to the user when time is excluded. */
  message: string | null;
}

export interface SubjectTotal {
  subject_id: string;
  name: string;
  color_hex: string;
  verified_seconds: number;
  manual_seconds: number;
  total_seconds: number;
}

export interface DailySummary {
  date: string;
  timezone: string;
  verified_seconds: number;
  manual_seconds: number;
  excluded_seconds: number;
  total_seconds: number;
  goal_minutes: number;
  goal_progress: number;
  session_count: number;
  current_streak_days: number;
  tasks_total: number;
  tasks_completed: number;
  planned_minutes: number;
  subjects: SubjectTotal[];
}

export interface DayTotals {
  day: string;
  verified_seconds: number;
  manual_seconds: number;
  excluded_seconds: number;
  total_seconds: number;
  session_count: number;
  is_scheduled: boolean;
  goal_met: boolean;
}

export interface WeeklySummary {
  week_start: string;
  week_end: string;
  timezone: string;
  verified_seconds: number;
  manual_seconds: number;
  excluded_seconds: number;
  total_seconds: number;
  goal_minutes: number;
  scheduled_days: number;
  scheduled_days_met: number;
  goal_completion_rate: number;
  average_session_seconds: number;
  session_count: number;
  days: DayTotals[];
  subjects: SubjectTotal[];
}

export interface StatisticsSummary {
  today: DailySummary;
  week: WeeklySummary;
}

export interface Task {
  id: string;
  subject_id: string | null;
  title: string;
  estimated_minutes: number;
  priority: TaskPriority;
  status: TaskStatus;
  sort_order: number;
  completed_at: string | null;
}

export interface DailyPlan {
  id: string;
  plan_date: string;
  reflection: string | null;
  tasks: Task[];
}

/** A safe public projection of another user. Never carries their email. */
export interface PublicUser {
  id: string;
  username: string;
  display_name: string;
  avatar_url: string | null;
  country_code: string | null;
  study_category: string;
}

export interface Friend {
  friendship_id: string;
  user: PublicUser;
  /** When the friendship was accepted, or null for legacy rows. */
  since: string | null;
}

export interface FriendRequest {
  friendship_id: string;
  /** "incoming" — they asked you; "outgoing" — you asked them. */
  direction: 'incoming' | 'outgoing';
  /** "pending", or "accepted" when a sent request auto-accepted a mirror one. */
  status: 'pending' | 'accepted';
  user: PublicUser;
  created_at: string;
}

export interface FriendRequests {
  incoming: FriendRequest[];
  outgoing: FriendRequest[];
}

export interface UserSearchResult {
  user: PublicUser;
  relationship: RelationshipState;
  /** Present when a relationship row already exists (to act on it directly). */
  friendship_id: string | null;
}

export interface GroupSummary {
  id: string;
  name: string;
  description: string | null;
  visibility: GroupVisibility;
  member_count: number;
  max_members: number;
  owner: PublicUser;
  created_at: string;
  /** The caller's role in this group, or null when they are not a member. */
  my_role: GroupRole | null;
}

export interface GroupMember {
  user: PublicUser;
  role: GroupRole;
  joined_at: string;
}

export interface GroupDetail {
  group: GroupSummary;
  rules: string | null;
  members: GroupMember[];
  /** Only present for owners and moderators. */
  invite_code: string | null;
}

export interface GroupInvitation {
  id: string;
  group: GroupSummary;
  inviter: PublicUser;
  expires_at: string;
  created_at: string;
}

export interface UserPresence {
  user: PublicUser;
  state: PresenceState;
  /** Null when the user hides their subject or is not studying. */
  subject_id: string | null;
  started_at: string | null;
  updated_at: string;
}

// ---------------------------------------------------------------- realtime

/** Short-lived credential for opening the realtime socket. Never the access token. */
export interface RealtimeTicket {
  ticket: string;
  expires_in: number;
}

export type ReactionEmoji = 'clap' | 'fire' | 'muscle' | 'sparkles' | 'heart';

/** The trimmed user shape carried by socket events (no country code, no email). */
export interface RealtimeUser {
  id: string;
  username: string;
  display_name: string;
  avatar_url: string | null;
  study_category: string;
}

export interface PresenceChangedEvent {
  event: 'presence.changed';
  data: { user: RealtimeUser; state: PresenceState | 'offline'; at: string };
}

export interface ReactionCreatedEvent {
  event: 'reaction.created';
  data: { from: RealtimeUser; emoji: ReactionEmoji; at: string };
}

export interface SubscriptionAckEvent {
  event: 'subscribed' | 'unsubscribed';
  data: { channels: string[] };
}

export interface PongEvent {
  event: 'pong';
}

export type RealtimeEvent =
  PresenceChangedEvent | ReactionCreatedEvent | SubscriptionAckEvent | PongEvent;

// ---------------------------------------------------------------- league

export type EnrollmentPlacement = 'provisional' | 'ranked' | 'unranked';
export type SeasonOutcome = 'promoted' | 'retained' | 'relegated' | 'unranked';

export interface WeekPoints {
  week_index: number;
  points: number;
}

export interface LeagueStanding {
  season_id: string;
  season_name: string;
  starts_on: string;
  ends_on: string;
  status: string;
  division_tier: number;
  division_name: string;
  cohort_id: string;
  cohort_label: string;
  category_name: string;
  placement: EnrollmentPlacement;
  rank: number;
  cohort_size: number;
  total_points: number;
  weeks: WeekPoints[];
}

export interface LeaderboardEntry {
  rank: number;
  user: PublicUser;
  total_points: number;
  placement: EnrollmentPlacement;
  is_me: boolean;
}

export interface ScoreComponent {
  name: string;
  points: number;
  max_points: number;
  detail: Record<string, unknown>;
}

export interface ScoreBreakdown {
  week_index: number;
  week_start: string;
  total_points: number;
  scoring_version: string;
  components: ScoreComponent[];
  excluded_seconds: number;
  exclusion_reasons: string[];
}

export interface LeagueMission {
  id: string;
  slug: string;
  title: string;
  description: string;
  target: number;
  reward_points: number;
  progress: number;
  completed: boolean;
}

export interface SeasonHistoryEntry {
  season_id: string;
  season_name: string;
  division_name: string;
  total_points: number;
  final_rank: number | null;
  outcome: SeasonOutcome | null;
}

// ---------------------------------------------------------------- goals

export type GoalStatus = 'active' | 'completed' | 'archived';

export interface GoalMilestone {
  title: string;
  target_date: string | null;
  done: boolean;
}

export interface Goal {
  id: string;
  title: string;
  target_date: string | null;
  target_weekly_minutes: number;
  subject_ids: string[];
  milestones: GoalMilestone[];
  description: string | null;
  status: GoalStatus;
  completed_at: string | null;
  days_remaining: number | null;
  is_overdue: boolean;
  week_verified_minutes: number;
  weekly_progress: number;
  milestones_total: number;
  milestones_done: number;
}

// ---------------------------------------------------------------- yearly insights

export interface HeatmapDay {
  day: string;
  verified_seconds: number;
  goal_met: boolean;
}

export interface MonthTotals {
  month: string;
  verified_seconds: number;
  session_count: number;
  active_days: number;
}

export interface YearlyInsights {
  year: number;
  timezone: string;
  verified_seconds: number;
  manual_seconds: number;
  total_seconds: number;
  session_count: number;
  active_days: number;
  longest_streak_days: number;
  busiest_day: string | null;
  months: MonthTotals[];
  heatmap: HeatmapDay[];
  subjects: SubjectTotal[];
}

// ---------------------------------------------------------------- community

export type PostTopic =
  'general' | 'motivation' | 'study_tips' | 'resources' | 'wins' | 'accountability' | 'questions';

export type PostReactionEmoji = 'like' | 'insightful' | 'celebrate' | 'support' | 'curious';

export interface CommunityPost {
  id: string;
  author: PublicUser;
  topic: PostTopic;
  title: string;
  body: string;
  created_at: string;
  comment_count: number;
  reaction_count: number;
  my_reaction: PostReactionEmoji | null;
  bookmarked: boolean;
}

export interface CommunityComment {
  id: string;
  author: PublicUser;
  body: string;
  created_at: string;
}

export interface CommunityPostDetail {
  post: CommunityPost;
  comments: CommunityComment[];
}
