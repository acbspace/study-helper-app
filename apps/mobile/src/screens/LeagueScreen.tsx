/**
 * League — where you stand this season, and exactly why.
 *
 * Three legitimate states, none of them errors: no season is running, you have not joined
 * this season yet, or you are ranked. The scoring rules stay on screen in every state,
 * because a competitive score nobody can explain is a score nobody trusts — and the fairness
 * rules (capped overshoot, no credit for manual time) are the product's whole argument.
 */

import React from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import {
  ApiError,
  type LeaderboardEntry,
  type LeagueMission,
  type ScoreComponent,
} from '@study-league/api-client';
import { spacing } from '@study-league/design-tokens';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { EmptyState, LoadingState } from '@/components/StateViews';
import { ProgressBar } from '@/components/ProgressBar';
import { Text } from '@/components/Text';
import {
  useEnrollInLeague,
  useLeagueBreakdown,
  useLeagueLeaderboard,
  useLeagueMissions,
  useLeagueStanding,
} from '@/features/api/queries';
import { useTheme } from '@/theme/ThemeProvider';

const COMPONENT_LABELS: Record<string, string> = {
  goal_completion: 'Goal completion',
  consistency: 'Consistency',
  focus_sessions: 'Focus sessions',
  task_completion: 'Planned tasks',
  group_participation: 'Group participation',
};

function errorCode(error: unknown): string | null {
  return error instanceof ApiError ? error.code : null;
}

export function LeagueScreen(): React.ReactElement {
  const standing = useLeagueStanding();
  const enrolled = standing.isSuccess;
  const leaderboard = useLeagueLeaderboard(enrolled);
  const breakdown = useLeagueBreakdown(enrolled);
  const missions = useLeagueMissions(enrolled);
  const enroll = useEnrollInLeague();

  if (standing.isLoading) return <LoadingState label="Loading your league…" />;

  const code = errorCode(standing.error);

  return (
    <ScrollView testID="league-screen" contentContainerStyle={styles.content}>
      {code === 'no_active_season' ? (
        <Card testID="league-no-season">
          <Text variant="heading">No season is running</Text>
          <Text variant="body" color="secondary">
            Seasons last four weeks. When the next one opens you will be placed in a cohort of
            20–30 students with similar goals.
          </Text>
        </Card>
      ) : null}

      {code === 'not_enrolled' ? (
        <Card testID="league-join">
          <Text variant="heading">Join this season</Text>
          <Text variant="body" color="secondary">
            You will be placed in a cohort with students in your category, starting in Bronze.
            Your first season is provisional.
          </Text>
          {enroll.isError ? (
            <Text variant="caption" color="danger" accessibilityRole="alert">
              Could not join the season. Please try again.
            </Text>
          ) : null}
          <Button
            testID="league-enroll"
            label="Join the league"
            onPress={() => enroll.mutate()}
            loading={enroll.isPending}
          />
        </Card>
      ) : null}

      {standing.data ? (
        <>
          <StandingCard entry={standing.data} />
          <LeaderboardCard
            entries={leaderboard.data ?? []}
            isLoading={leaderboard.isLoading}
          />
          <BreakdownCard
            components={breakdown.data?.components ?? []}
            totalPoints={breakdown.data?.total_points ?? 0}
            missing={errorCode(breakdown.error) === 'score_not_found'}
            isLoading={breakdown.isLoading}
          />
          <MissionsCard missions={missions.data ?? []} />
        </>
      ) : null}

      <ScoringRulesCard />

      <Card testID="league-fairness">
        <Text variant="heading">Fair by design</Text>
        <Text variant="body" color="secondary">
          Studying beyond your goal earns sharply reduced credit, so no one can out-grind a
          consistent week. Rest days you scheduled are never penalised. Manually entered time
          appears in your own statistics but earns no League Points, and time flagged by
          integrity checks is excluded with an explanation you can read.
        </Text>
      </Card>
    </ScrollView>
  );
}

function StandingCard({
  entry,
}: {
  entry: NonNullable<ReturnType<typeof useLeagueStanding>['data']>;
}): React.ReactElement {
  return (
    <Card testID="league-standing">
      <Text variant="label" color="secondary">
        {entry.division_name} · {entry.category_name}
      </Text>
      <Text variant="title" tabular>
        {entry.total_points} points
      </Text>
      <Text variant="body" color="secondary">
        Rank {entry.rank} of {entry.cohort_size} · {entry.cohort_label}
      </Text>
      {entry.placement === 'provisional' ? (
        <Text variant="caption" color="secondary">
          Provisional placement — your first season settles your division.
        </Text>
      ) : null}
      {entry.weeks.length > 0 ? (
        <View style={styles.weekRow}>
          {entry.weeks.map((week) => (
            <View key={week.week_index} style={styles.week}>
              <Text variant="caption" color="secondary">
                W{week.week_index + 1}
              </Text>
              <Text variant="label" tabular>
                {week.points}
              </Text>
            </View>
          ))}
        </View>
      ) : null}
    </Card>
  );
}

function LeaderboardCard({
  entries,
  isLoading,
}: {
  entries: LeaderboardEntry[];
  isLoading: boolean;
}): React.ReactElement {
  const { theme } = useTheme();
  return (
    <Card testID="league-leaderboard">
      <Text variant="heading">Cohort standings</Text>
      {isLoading && entries.length === 0 ? (
        <Text variant="caption" color="secondary">
          Loading…
        </Text>
      ) : null}
      {entries.map((entry) => (
        <View
          key={entry.user.id}
          style={[
            styles.row,
            entry.is_me ? { backgroundColor: theme.accentMuted, borderRadius: 8 } : null,
          ]}
        >
          <Text variant="label" tabular color="secondary" style={styles.rank}>
            {entry.rank}
          </Text>
          <Text variant="body" style={styles.flex}>
            {entry.user.display_name}
            {entry.is_me ? ' (you)' : ''}
          </Text>
          <Text variant="label" tabular>
            {entry.total_points}
          </Text>
        </View>
      ))}
      {!isLoading && entries.length === 0 ? (
        <EmptyState title="No standings yet" description="Scores appear once the week is scored." />
      ) : null}
    </Card>
  );
}

function BreakdownCard({
  components,
  totalPoints,
  missing,
  isLoading,
}: {
  components: ScoreComponent[];
  totalPoints: number;
  missing: boolean;
  isLoading: boolean;
}): React.ReactElement {
  const { theme } = useTheme();
  return (
    <Card testID="league-breakdown">
      <Text variant="heading">This week&apos;s points</Text>
      {missing ? (
        <Text variant="body" color="secondary">
          This week has not been scored yet. Points appear as the week is scored.
        </Text>
      ) : null}
      {isLoading && components.length === 0 && !missing ? (
        <Text variant="caption" color="secondary">
          Loading…
        </Text>
      ) : null}
      {components.length > 0 ? (
        <Text variant="body" color="secondary">
          {totalPoints} of 1,000 this week
        </Text>
      ) : null}
      {components.map((component) => (
        <View key={component.name} style={styles.componentRow}>
          <View style={styles.componentHeader}>
            <Text variant="label" style={styles.flex}>
              {COMPONENT_LABELS[component.name] ?? component.name}
            </Text>
            <Text variant="label" tabular color="secondary">
              {component.points}/{component.max_points}
            </Text>
          </View>
          <ProgressBar
            progress={component.max_points === 0 ? 0 : component.points / component.max_points}
            color={theme.accent}
            height={6}
            accessibilityLabel={`${COMPONENT_LABELS[component.name] ?? component.name}: ${component.points} of ${component.max_points} points`}
          />
        </View>
      ))}
    </Card>
  );
}

function MissionsCard({ missions }: { missions: LeagueMission[] }): React.ReactElement | null {
  const { theme } = useTheme();
  if (missions.length === 0) return null;

  return (
    <Card testID="league-missions">
      <Text variant="heading">Missions</Text>
      <Text variant="body" color="secondary">
        Optional nudges toward healthier habits — never toward more hours.
      </Text>
      {missions.map((mission) => (
        <View key={mission.id} style={styles.componentRow}>
          <View style={styles.componentHeader}>
            <Text variant="label" style={styles.flex}>
              {mission.completed ? '✓ ' : ''}
              {mission.title}
            </Text>
            <Text variant="label" tabular color={mission.completed ? 'verified' : 'secondary'}>
              {Math.min(mission.progress, mission.target)}/{mission.target}
            </Text>
          </View>
          <Text variant="caption" color="secondary">
            {mission.description}
          </Text>
          <ProgressBar
            progress={mission.target === 0 ? 0 : mission.progress / mission.target}
            color={mission.completed ? theme.verified : theme.accent}
            height={6}
            accessibilityLabel={`${mission.title}: ${mission.progress} of ${mission.target}`}
          />
        </View>
      ))}
    </Card>
  );
}

function ScoringRulesCard(): React.ReactElement {
  const rules: { label: string; points: number; detail: string }[] = [
    { label: 'Goal completion', points: 400, detail: 'Meeting the daily goal you set' },
    { label: 'Consistency', points: 250, detail: 'Studying on the days you scheduled' },
    { label: 'Focus sessions', points: 150, detail: 'Sessions you finished as planned' },
    { label: 'Planned tasks', points: 150, detail: 'Completing what you planned' },
    { label: 'Group participation', points: 50, detail: 'Encouraging your study group' },
  ];

  return (
    <Card testID="league-scoring">
      <Text variant="heading">How League Points work</Text>
      <Text variant="body" color="secondary">
        1,000 points per week, awarded for sustainable habits:
      </Text>
      {rules.map((rule) => (
        <View key={rule.label} style={styles.row}>
          <View style={styles.flex}>
            <Text variant="label">{rule.label}</Text>
            <Text variant="caption" color="secondary">
              {rule.detail}
            </Text>
          </View>
          <Text variant="label" tabular color="accent">
            {rule.points}
          </Text>
        </View>
      ))}
    </Card>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xxxl },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.xs },
  rank: { width: 24 },
  weekRow: { flexDirection: 'row', gap: spacing.lg, marginTop: spacing.xs },
  week: { alignItems: 'center' },
  componentRow: { gap: spacing.xxs },
  componentHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  flex: { flex: 1 },
});
