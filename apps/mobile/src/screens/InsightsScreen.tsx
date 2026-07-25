/**
 * Insights — weekly review.
 *
 * Deliberately reports verified and manual time separately and marks scheduled days:
 * the point is an honest picture of the week, not the largest possible number.
 */

import React from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { useRouter } from 'expo-router';

import { spacing } from '@study-league/design-tokens';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { EmptyState, ErrorState, LoadingState } from '@/components/StateViews';
import { ProgressBar } from '@/components/ProgressBar';
import { Text } from '@/components/Text';
import { useStatisticsSummary, useYearlyInsights } from '@/features/api/queries';
import { formatDurationLong } from '@/features/timer/timeline';
import { useTheme } from '@/theme/ThemeProvider';

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export function InsightsScreen(): React.ReactElement {
  const { theme } = useTheme();
  const router = useRouter();
  const summary = useStatisticsSummary();
  const yearly = useYearlyInsights();

  if (summary.isLoading && !summary.data) return <LoadingState label="Loading insights…" />;

  if (summary.isError && !summary.data) {
    return (
      <ErrorState
        testID="insights-error"
        description="We could not load your statistics."
        onRetry={() => void summary.refetch()}
      />
    );
  }

  const week = summary.data?.week;
  if (!week) return <EmptyState title="No data yet" />;

  const busiest = Math.max(...week.days.map((day) => day.verified_seconds), 1);

  return (
    <ScrollView testID="insights-screen" contentContainerStyle={styles.content}>
      <Card testID="insights-week-total">
        <Text variant="label" color="secondary">
          Week of {week.week_start} · {week.timezone}
        </Text>
        <Text variant="title" tabular>
          {formatDurationLong(week.verified_seconds)} verified
        </Text>
        {week.manual_seconds > 0 ? (
          <Text variant="caption" color="manual">
            + {formatDurationLong(week.manual_seconds)} entered manually
          </Text>
        ) : null}
        {week.excluded_seconds > 0 ? (
          <Text variant="caption" color="secondary">
            {formatDurationLong(week.excluded_seconds)} excluded from competition
          </Text>
        ) : null}
      </Card>

      {/* Day-by-day bars: scheduled days are labelled so rest days read as intentional. */}
      <Card testID="insights-days">
        <Text variant="heading">Daily breakdown</Text>
        {week.days.map((day, index) => (
          <View key={day.day} style={styles.dayRow}>
            <Text variant="caption" color="secondary" style={styles.dayLabel}>
              {DAY_LABELS[index]}
            </Text>
            <View style={styles.barContainer}>
              <ProgressBar
                progress={day.verified_seconds / busiest}
                color={day.goal_met ? theme.verified : theme.accent}
                height={8}
                accessibilityLabel={`${DAY_LABELS[index]}: ${formatDurationLong(day.verified_seconds)}${
                  day.is_scheduled ? ', scheduled study day' : ''
                }${day.goal_met ? ', goal met' : ''}`}
              />
            </View>
            <Text variant="caption" tabular color="secondary" style={styles.dayValue}>
              {formatDurationLong(day.verified_seconds)}
            </Text>
          </View>
        ))}
      </Card>

      <Card testID="insights-metrics">
        <Text variant="heading">This week</Text>
        <Metric
          label="Goal days met"
          value={`${week.scheduled_days_met} of ${week.scheduled_days}`}
        />
        <Metric label="Goal completion" value={`${Math.round(week.goal_completion_rate * 100)}%`} />
        <Metric label="Sessions" value={String(week.session_count)} />
        <Metric label="Average session" value={formatDurationLong(week.average_session_seconds)} />
      </Card>

      {yearly.data ? (
        <Card testID="insights-year">
          <Text variant="heading">This year</Text>
          <Metric label="Verified time" value={formatDurationLong(yearly.data.verified_seconds)} />
          <Metric label="Active days" value={String(yearly.data.active_days)} />
          <Metric label="Longest streak" value={`${yearly.data.longest_streak_days} days`} />
          {/* A compact 12-month bar of verified time. */}
          <View style={styles.monthsRow}>
            {yearly.data.months.map((month) => {
              const busiest = Math.max(...yearly.data!.months.map((m) => m.verified_seconds), 1);
              return (
                <View key={month.month} style={styles.monthCol}>
                  <View style={styles.monthTrack}>
                    <View
                      style={[
                        styles.monthFill,
                        {
                          backgroundColor: theme.verified,
                          height: `${Math.round((month.verified_seconds / busiest) * 100)}%`,
                        },
                      ]}
                    />
                  </View>
                  <Text variant="caption" color="secondary" style={styles.monthLabel}>
                    {month.month.slice(5)}
                  </Text>
                </View>
              );
            })}
          </View>
        </Card>
      ) : null}

      <Card testID="insights-more">
        <Text variant="heading">Go deeper</Text>
        <View style={styles.linkRow}>
          <Button label="Goals" variant="secondary" onPress={() => router.push('/goals')} />
          <Button label="Community" variant="secondary" onPress={() => router.push('/community')} />
        </View>
      </Card>

      <Card testID="insights-subjects">
        <Text variant="heading">By subject</Text>
        {week.subjects.length > 0 ? (
          week.subjects.map((subject) => (
            <View key={subject.subject_id} style={styles.subjectRow}>
              <View style={[styles.swatch, { backgroundColor: subject.color_hex }]} />
              <Text variant="body" style={styles.flex}>
                {subject.name}
              </Text>
              <Text variant="label" tabular color="secondary">
                {formatDurationLong(subject.total_seconds)}
              </Text>
            </View>
          ))
        ) : (
          <EmptyState title="No sessions this week" description="Start a timer to see insights." />
        )}
      </Card>
    </ScrollView>
  );
}

function Metric({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <View style={styles.metricRow} accessible accessibilityLabel={`${label}: ${value}`}>
      <Text variant="body" color="secondary">
        {label}
      </Text>
      <Text variant="label" tabular>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xxxl },
  dayRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  dayLabel: { width: 36 },
  barContainer: { flex: 1 },
  dayValue: { width: 56, textAlign: 'right' },
  metricRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  linkRow: { flexDirection: 'row', gap: spacing.md },
  monthsRow: { flexDirection: 'row', alignItems: 'flex-end', gap: spacing.xs, height: 72 },
  monthCol: { flex: 1, alignItems: 'center', gap: spacing.xxs },
  monthTrack: { width: '100%', height: 48, justifyContent: 'flex-end' },
  monthFill: { width: '100%', borderRadius: 2, minHeight: 2 },
  monthLabel: { fontSize: 9 },
  subjectRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  swatch: { width: 12, height: 12, borderRadius: 6 },
  flex: { flex: 1 },
});
