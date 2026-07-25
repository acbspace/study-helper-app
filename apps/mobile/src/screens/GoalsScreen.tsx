/**
 * Goals — long-horizon commitments with a countdown and weekly pacing.
 *
 * The countdown is the point: "37 days left" reframes a vague ambition as something with a
 * clock on it. Pacing is measured against the weekly commitment the user set for themselves,
 * from verified time only — the same honesty the rest of the app keeps.
 */

import React, { useState } from 'react';
import { ScrollView, StyleSheet, TextInput, View } from 'react-native';

import type { Goal } from '@study-league/api-client';
import { minTouchTarget, radius, spacing } from '@study-league/design-tokens';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { EmptyState, ErrorState, LoadingState } from '@/components/StateViews';
import { ProgressBar } from '@/components/ProgressBar';
import { Text } from '@/components/Text';
import { useCreateGoal, useDeleteGoal, useGoals, useUpdateGoal } from '@/features/api/queries';
import { useTheme } from '@/theme/ThemeProvider';

export function GoalsScreen(): React.ReactElement {
  const goals = useGoals();

  if (goals.isLoading && !goals.data) return <LoadingState label="Loading goals…" />;
  if (goals.isError && !goals.data) {
    return <ErrorState testID="goals-error" onRetry={() => void goals.refetch()} />;
  }

  const list = goals.data ?? [];

  return (
    <ScrollView testID="goals-screen" contentContainerStyle={styles.content}>
      <NewGoalCard />
      {list.length === 0 ? (
        <Card>
          <EmptyState
            title="No goals yet"
            description="Set a target date and a weekly commitment, and watch the countdown."
          />
        </Card>
      ) : (
        list.map((goal) => <GoalCard key={goal.id} goal={goal} />)
      )}
    </ScrollView>
  );
}

function NewGoalCard(): React.ReactElement {
  const { theme, fontSize } = useTheme();
  const create = useCreateGoal();
  const [title, setTitle] = useState('');
  const [weekly, setWeekly] = useState('');
  const trimmed = title.trim();

  const handleCreate = () => {
    if (!trimmed) return;
    const minutes = Number.parseInt(weekly, 10);
    create.mutate(
      {
        title: trimmed,
        target_weekly_minutes: Number.isFinite(minutes) && minutes > 0 ? minutes : 0,
      },
      {
        onSuccess: () => {
          setTitle('');
          setWeekly('');
        },
      },
    );
  };

  return (
    <Card>
      <Text variant="heading">New goal</Text>
      <TextInput
        testID="goal-title-input"
        value={title}
        onChangeText={setTitle}
        placeholder="e.g. Pass the certification"
        placeholderTextColor={theme.textSecondary}
        accessibilityLabel="Goal title"
        maxLength={120}
        style={inputStyle(theme, fontSize)}
      />
      <TextInput
        testID="goal-weekly-input"
        value={weekly}
        onChangeText={setWeekly}
        placeholder="Weekly minutes (optional)"
        placeholderTextColor={theme.textSecondary}
        accessibilityLabel="Weekly commitment in minutes"
        keyboardType="number-pad"
        maxLength={5}
        style={inputStyle(theme, fontSize)}
      />
      <Button
        testID="create-goal"
        label="Add goal"
        onPress={handleCreate}
        disabled={!trimmed}
        loading={create.isPending}
      />
    </Card>
  );
}

function GoalCard({ goal }: { goal: Goal }): React.ReactElement {
  const { theme } = useTheme();
  const update = useUpdateGoal();
  const remove = useDeleteGoal();

  const countdown =
    goal.days_remaining === null
      ? null
      : goal.days_remaining >= 0
        ? `${goal.days_remaining} day${goal.days_remaining === 1 ? '' : 's'} left`
        : `${-goal.days_remaining} day${goal.days_remaining === -1 ? '' : 's'} overdue`;

  return (
    <Card testID={`goal-${goal.id}`}>
      <Text variant="heading">{goal.title}</Text>
      {countdown ? (
        <Text variant="label" color={goal.is_overdue ? 'danger' : 'accent'} tabular>
          {countdown}
        </Text>
      ) : null}

      {goal.target_weekly_minutes > 0 ? (
        <View style={styles.progressBlock}>
          <View style={styles.rowBetween}>
            <Text variant="caption" color="secondary">
              This week
            </Text>
            <Text variant="caption" tabular color="secondary">
              {goal.week_verified_minutes} / {goal.target_weekly_minutes} min
            </Text>
          </View>
          <ProgressBar
            progress={goal.weekly_progress}
            color={theme.verified}
            height={8}
            accessibilityLabel={`Weekly progress: ${Math.round(goal.weekly_progress * 100)} percent`}
          />
        </View>
      ) : null}

      {goal.milestones_total > 0 ? (
        <Text variant="caption" color="secondary">
          Milestones: {goal.milestones_done}/{goal.milestones_total}
        </Text>
      ) : null}

      <View style={styles.actions}>
        <Button
          label="Mark done"
          variant="secondary"
          onPress={() => update.mutate({ goalId: goal.id, changes: { status: 'completed' } })}
          loading={update.isPending}
        />
        <Button
          label="Delete"
          variant="ghost"
          onPress={() => remove.mutate(goal.id)}
          loading={remove.isPending}
          accessibilityHint={`Deletes the goal ${goal.title}`}
        />
      </View>
    </Card>
  );
}

function inputStyle(
  theme: ReturnType<typeof useTheme>['theme'],
  fontSize: ReturnType<typeof useTheme>['fontSize'],
) {
  return {
    minHeight: minTouchTarget,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surfaceMuted,
    color: theme.textPrimary,
    paddingHorizontal: spacing.md,
    fontSize: fontSize('body'),
  } as const;
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xxxl },
  progressBlock: { gap: spacing.xxs },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  actions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xs },
});
