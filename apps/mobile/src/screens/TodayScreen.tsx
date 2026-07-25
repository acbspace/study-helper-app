/**
 * Today — the app's home.
 *
 * Answers, in one glance and without scrolling: how much verified time today, how close to
 * the goal, what subjects, what tasks remain, the current streak, and one obvious way to
 * start studying.
 */

import React, { useCallback, useMemo, useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, View } from 'react-native';

import { spacing } from '@study-league/design-tokens';
import { ApiError } from '@study-league/api-client';
import { useRouter } from 'expo-router';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { ProgressBar } from '@/components/ProgressBar';
import { EmptyState, ErrorState, LoadingState, OfflineNotice } from '@/components/StateViews';
import { Text } from '@/components/Text';
import { useStatisticsSummary, useTodayPlan, useUpdateTask } from '@/features/api/queries';
import { useSync } from '@/features/sync/useSync';
import { formatDurationAccessible, formatDurationLong } from '@/features/timer/timeline';
import { useTimerStore } from '@/features/timer/timerStore';
import { useTheme } from '@/theme/ThemeProvider';

export function TodayScreen(): React.ReactElement {
  const router = useRouter();
  const { theme } = useTheme();
  const summary = useStatisticsSummary();
  const plan = useTodayPlan();
  const updateTask = useUpdateTask();
  const sync = useSync();
  const timerStatus = useTimerStore((state) => state.state.status);
  const [refreshing, setRefreshing] = useState(false);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([summary.refetch(), plan.refetch(), sync.syncNow()]);
    setRefreshing(false);
  }, [plan, summary, sync]);

  const isOffline = useMemo(
    () => summary.error instanceof ApiError && summary.error.code === 'network_error',
    [summary.error],
  );

  if (summary.isLoading && !summary.data) {
    return <LoadingState label="Loading today…" />;
  }

  if (summary.isError && !summary.data) {
    return (
      <ErrorState
        testID="today-error"
        title={isOffline ? "You're offline" : 'Could not load today'}
        description={
          isOffline
            ? 'Your timer still works. Totals will appear when you reconnect.'
            : 'Pull to refresh, or try again in a moment.'
        }
        onRetry={() => void summary.refetch()}
      />
    );
  }

  const today = summary.data?.today;
  const week = summary.data?.week;
  const pendingTasks = plan.data?.tasks.filter((task) => task.status === 'pending') ?? [];

  return (
    <ScrollView
      testID="today-screen"
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
    >
      {isOffline || sync.pending > 0 ? (
        <OfflineNotice testID="today-offline" pendingCount={sync.pending} />
      ) : null}

      {/* Verified time and goal progress: the headline number. */}
      <Card testID="today-progress">
        <Text variant="label" color="secondary">
          Verified study time today
        </Text>
        <Text
          variant="display"
          tabular
          accessibilityLabel={`${formatDurationAccessible(today?.verified_seconds ?? 0)} of verified study time today`}
        >
          {formatDurationLong(today?.verified_seconds ?? 0)}
        </Text>

        <ProgressBar
          testID="today-goal-progress"
          progress={today?.goal_progress ?? 0}
          color={theme.verified}
          accessibilityLabel={`Daily goal progress: ${Math.round((today?.goal_progress ?? 0) * 100)} percent of ${today?.goal_minutes ?? 0} minutes`}
        />
        <View style={styles.row}>
          <Text variant="caption" color="secondary">
            Goal {formatDurationLong((today?.goal_minutes ?? 0) * 60)}
          </Text>
          {today && today.manual_seconds > 0 ? (
            // Manual time is shown, but visibly separated from verified time.
            <Text variant="caption" color="manual">
              + {formatDurationLong(today.manual_seconds)} manual
            </Text>
          ) : null}
        </View>
      </Card>

      <View style={styles.statRow}>
        <Card style={styles.statCard} testID="today-streak">
          <Text variant="caption" color="secondary">
            Streak
          </Text>
          <Text variant="title" tabular>
            {today?.current_streak_days ?? 0}
          </Text>
          <Text variant="caption" color="secondary">
            {today?.current_streak_days === 1 ? 'day' : 'days'}
          </Text>
        </Card>
        <Card style={styles.statCard} testID="today-week">
          <Text variant="caption" color="secondary">
            This week
          </Text>
          <Text variant="title" tabular>
            {formatDurationLong(week?.verified_seconds ?? 0)}
          </Text>
          <Text variant="caption" color="secondary">
            {week?.scheduled_days_met ?? 0}/{week?.scheduled_days ?? 0} goal days
          </Text>
        </Card>
      </View>

      <Button
        testID="today-start-studying"
        label={timerStatus === 'active' ? 'Back to your session' : 'Start studying'}
        size="large"
        onPress={() => router.push('/(tabs)/timer')}
        accessibilityHint="Opens the study timer"
      />

      {/* Subject breakdown */}
      <Card testID="today-subjects">
        <Text variant="heading">Subjects</Text>
        {today && today.subjects.length > 0 ? (
          today.subjects.map((subject) => (
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
          <EmptyState
            testID="today-subjects-empty"
            title="No study time yet"
            description="Start a session to see your subject breakdown."
          />
        )}
      </Card>

      {/* Tasks */}
      <Card testID="today-tasks">
        <View style={styles.row}>
          <Text variant="heading">Tasks</Text>
          <Text variant="caption" color="secondary">
            {today?.tasks_completed ?? 0}/{today?.tasks_total ?? 0} done
          </Text>
        </View>

        {plan.isLoading ? (
          <LoadingState label="Loading tasks…" />
        ) : pendingTasks.length > 0 ? (
          pendingTasks.slice(0, 5).map((task) => (
            <View key={task.id} style={styles.subjectRow}>
              <Text variant="body" style={styles.flex}>
                {task.title}
              </Text>
              <Button
                label="Done"
                variant="ghost"
                onPress={() => updateTask.mutate({ taskId: task.id, changes: { status: 'done' } })}
                accessibilityHint={`Marks ${task.title} as complete`}
              />
            </View>
          ))
        ) : (
          <EmptyState
            testID="today-tasks-empty"
            title={today?.tasks_total ? 'All tasks complete' : 'No tasks planned'}
            description={
              today?.tasks_total
                ? 'Nice work — everything you planned today is done.'
                : 'Plan a few tasks to keep your study time focused.'
            }
          />
        )}
      </Card>

      {/* League placeholder: the slot is real, the data arrives in M3. */}
      <Card testID="today-league">
        <Text variant="heading">Study League</Text>
        <Text variant="body" color="secondary">
          Seasonal leagues open soon. League Points reward consistency and finishing what you
          planned — not raw hours.
        </Text>
      </Card>

      {/* Manage: the only route to Settings, and to Subjects, which nothing else linked to. */}
      <Card testID="today-manage">
        <Text variant="heading">Manage</Text>
        <View style={styles.linkRow}>
          <Button
            testID="today-open-subjects"
            label="Subjects"
            variant="secondary"
            onPress={() => router.push('/subjects')}
            style={styles.flex}
          />
          <Button
            testID="today-open-settings"
            label="Settings"
            variant="secondary"
            onPress={() => router.push('/settings')}
            accessibilityHint="Goals, study days, privacy, and account"
            style={styles.flex}
          />
        </View>
      </Card>

      {sync.messages.length > 0 ? (
        <Card testID="today-sync-messages">
          <Text variant="label">About your recent sessions</Text>
          {sync.messages.map((message) => (
            <Text key={message} variant="caption" color="secondary">
              {message}
            </Text>
          ))}
          <Button label="Got it" variant="ghost" onPress={sync.dismissMessages} />
        </Card>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xxxl },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  statRow: { flexDirection: 'row', gap: spacing.md },
  statCard: { flex: 1 },
  subjectRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  linkRow: { flexDirection: 'row', gap: spacing.md },
  swatch: { width: 12, height: 12, borderRadius: 6 },
  flex: { flex: 1 },
});
