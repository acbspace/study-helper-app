/**
 * The dashboard: a signed-in student's week at a glance — verified time, streak, this week's
 * shape, their league standing, and which friends are studying right now.
 *
 * Read-only and honest: verified and manual time stay separate, and league/presence "empty"
 * states (no season, not enrolled, nobody online) are rendered as normal, not as errors.
 */

import type { ReactElement } from 'react';

import { ApiError } from '@study-league/api-client';

import { Button, Card, Meter, Spinner, StatTile } from '@/components/ui';
import { useAuth } from '@/features/auth/AuthProvider';
import {
  useFriendsPresence,
  useLeagueStanding,
  useStatisticsSummary,
} from '@/features/api/queries';
import { formatDuration } from '@/lib/format';
import { spacing, theme } from '@/theme';

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export function Dashboard(): ReactElement {
  const { user, signOut } = useAuth();
  const stats = useStatisticsSummary();

  return (
    <div style={{ minHeight: '100vh', background: theme.background }}>
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: `${spacing.lg}px ${spacing.xl}px`,
          borderBottom: `1px solid ${theme.border}`,
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: 20, color: theme.textPrimary }}>Study League</h1>
          <p style={{ margin: 0, color: theme.textSecondary, fontSize: 14 }}>
            {user ? `Signed in as ${user.profile.display_name}` : ''}
          </p>
        </div>
        <Button label="Sign out" variant="ghost" onClick={() => void signOut()} />
      </header>

      <main
        style={{
          maxWidth: 1040,
          margin: '0 auto',
          padding: spacing.xl,
          display: 'flex',
          flexDirection: 'column',
          gap: spacing.lg,
        }}
      >
        {stats.isLoading && !stats.data ? (
          <Spinner label="Loading your dashboard…" />
        ) : stats.isError && !stats.data ? (
          <Card testId="dashboard-error">
            <p style={{ color: theme.danger, margin: 0 }}>
              We could not load your statistics.
            </p>
            <Button label="Try again" variant="ghost" onClick={() => void stats.refetch()} />
          </Card>
        ) : stats.data ? (
          <StatsSection data={stats.data} />
        ) : null}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: spacing.lg }}>
          <LeagueCard />
          <PresenceCard />
        </div>
      </main>
    </div>
  );
}

function StatsSection({
  data,
}: {
  data: NonNullable<ReturnType<typeof useStatisticsSummary>['data']>;
}): ReactElement {
  const { today, week } = data;
  const busiest = Math.max(...week.days.map((d) => d.verified_seconds), 1);

  return (
    <>
      <div
        data-testid="dashboard-stats"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: spacing.lg,
        }}
      >
        <StatTile
          testId="stat-today"
          label="Verified today"
          value={formatDuration(today.verified_seconds)}
          accent
        />
        <StatTile label="Current streak" value={`${today.current_streak_days} days`} />
        <StatTile label="Verified this week" value={formatDuration(week.verified_seconds)} />
        <StatTile
          label="Goal days met"
          value={`${week.scheduled_days_met}/${week.scheduled_days}`}
        />
      </div>

      <Card testId="dashboard-week">
        <h2 style={{ margin: 0, fontSize: 17, color: theme.textPrimary }}>This week</h2>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: spacing.md, height: 140 }}>
          {week.days.map((day, index) => (
            <div key={day.day} style={{ flex: 1, textAlign: 'center' }}>
              <div style={{ height: 100, display: 'flex', alignItems: 'flex-end' }}>
                <div
                  title={formatDuration(day.verified_seconds)}
                  style={{
                    width: '100%',
                    height: `${Math.round((day.verified_seconds / busiest) * 100)}%`,
                    minHeight: 2,
                    borderRadius: 4,
                    background: day.goal_met ? theme.verified : theme.accent,
                  }}
                />
              </div>
              <span style={{ fontSize: 12, color: theme.textSecondary }}>{DAY_LABELS[index]}</span>
            </div>
          ))}
        </div>
        {week.manual_seconds > 0 ? (
          <span style={{ color: theme.manual, fontSize: 13 }}>
            + {formatDuration(week.manual_seconds)} entered manually (not counted competitively)
          </span>
        ) : null}
      </Card>
    </>
  );
}

function LeagueCard(): ReactElement {
  const league = useLeagueStanding();
  const code = league.error instanceof ApiError ? league.error.code : null;

  return (
    <Card testId="dashboard-league">
      <h2 style={{ margin: 0, fontSize: 17, color: theme.textPrimary }}>League</h2>
      {league.isLoading ? (
        <Spinner label="Loading…" />
      ) : code === 'no_active_season' ? (
        <p style={{ color: theme.textSecondary, margin: 0 }}>No season is running right now.</p>
      ) : code === 'not_enrolled' ? (
        <p style={{ color: theme.textSecondary, margin: 0 }}>
          You have not joined this season yet — open the mobile app to enroll.
        </p>
      ) : league.data ? (
        <>
          <span style={{ color: theme.textSecondary, fontSize: 13 }}>
            {league.data.division_name} · {league.data.category_name}
          </span>
          <span
            style={{ fontSize: 26, fontWeight: 700, color: theme.textPrimary, fontVariantNumeric: 'tabular-nums' }}
          >
            {league.data.total_points} points
          </span>
          <span style={{ color: theme.textSecondary, fontSize: 14 }}>
            Rank {league.data.rank} of {league.data.cohort_size}
          </span>
        </>
      ) : (
        <p style={{ color: theme.textSecondary, margin: 0 }}>League unavailable.</p>
      )}
    </Card>
  );
}

function PresenceCard(): ReactElement {
  const presence = useFriendsPresence();
  const rows = presence.data ?? [];

  return (
    <Card testId="dashboard-presence">
      <h2 style={{ margin: 0, fontSize: 17, color: theme.textPrimary }}>Friends studying now</h2>
      {rows.length === 0 ? (
        <p style={{ color: theme.textSecondary, margin: 0 }}>No friends are studying right now.</p>
      ) : (
        rows.map((row) => (
          <div
            key={row.user.id}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
          >
            <span style={{ color: theme.textPrimary }}>{row.user.display_name}</span>
            <span
              style={{
                color: row.state === 'studying' ? theme.verified : theme.streak,
                fontSize: 13,
              }}
            >
              {row.state === 'studying' ? 'Studying' : row.state === 'break' ? 'On a break' : 'Online'}
            </span>
          </div>
        ))
      )}
      <Meter progress={rows.length === 0 ? 0 : 1} color={theme.verified} />
    </Card>
  );
}
