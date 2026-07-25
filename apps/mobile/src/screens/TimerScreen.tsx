/**
 * The study timer.
 *
 * Shows elapsed time derived from persisted timestamps — leaving this screen, backgrounding
 * the app, or restarting the phone changes nothing about the running session.
 */

import React, { useMemo, useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { spacing, typography } from '@study-league/design-tokens';
import { useKeepAwake } from 'expo-keep-awake';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { EmptyState, LoadingState } from '@/components/StateViews';
import { Text } from '@/components/Text';
import { useSubjects } from '@/features/api/queries';
import { useSync } from '@/features/sync/useSync';
import {
  formatDuration,
  formatDurationAccessible,
  formatDurationLong,
} from '@/features/timer/timeline';
import { useTimerStore } from '@/features/timer/timerStore';
import { useTimerTick } from '@/features/timer/useTimerTick';
import { useTheme } from '@/theme/ThemeProvider';

export function TimerScreen(): React.ReactElement {
  const { theme, fontSize } = useTheme();
  const subjects = useSubjects();
  const sync = useSync();
  useTimerTick();
  // Studying with the screen on is the common case; sleeping mid-session is jarring.
  useKeepAwake();

  const timer = useTimerStore();
  const [selectedSubjectId, setSelectedSubjectId] = useState<string | null>(null);

  const activeSubject = useMemo(() => {
    const id = timer.subjectId ?? selectedSubjectId;
    return subjects.data?.find((subject) => subject.id === id) ?? null;
  }, [subjects.data, selectedSubjectId, timer.subjectId]);

  const isRunning = timer.state.status === 'active' || timer.state.status === 'paused';

  if (timer.isHydrating) {
    return <LoadingState label="Restoring your timer…" />;
  }

  if (subjects.isLoading && !subjects.data) {
    return <LoadingState label="Loading subjects…" />;
  }

  if (!isRunning && (subjects.data?.length ?? 0) === 0) {
    return (
      <EmptyState
        testID="timer-no-subjects"
        title="Create a subject first"
        description="Subjects let you see where your study time actually goes."
      />
    );
  }

  const handleStart = async () => {
    const subjectId = selectedSubjectId ?? subjects.data?.[0]?.id;
    if (!subjectId) return;
    await timer.start({ subjectId });
  };

  const handleStop = async () => {
    await timer.stop();
    // Push straight away when online; otherwise it waits safely in the outbox.
    await sync.syncNow();
  };

  return (
    <ScrollView testID="timer-screen" contentContainerStyle={styles.content}>
      <Card testID="timer-display">
        <Text variant="label" color="secondary" align="center">
          {activeSubject?.name ?? 'Select a subject'}
        </Text>

        <Text
          testID="timer-elapsed"
          tabular
          align="center"
          accessibilityLabel={`Elapsed: ${formatDurationAccessible(timer.state.elapsedSeconds)}`}
          // Announce only on demand: a per-second live region would be unusable.
          accessibilityLiveRegion="none"
          style={{
            fontSize: fontSize('timer'),
            lineHeight: fontSize('timer') * 1.1,
            fontWeight: typography.timer.weight,
            color: timer.state.status === 'active' ? theme.verified : theme.textPrimary,
          }}
        >
          {formatDuration(timer.state.elapsedSeconds)}
        </Text>

        <Text variant="caption" color="secondary" align="center">
          {timer.state.status === 'active'
            ? 'Recording — verified time'
            : timer.state.status === 'paused'
              ? 'Paused'
              : 'Ready when you are'}
        </Text>
      </Card>

      {timer.lastError ? (
        <Card testID="timer-error">
          <Text variant="caption" color="danger" accessibilityRole="alert">
            {timer.lastError}
          </Text>
        </Card>
      ) : null}

      {/* Controls */}
      <View style={styles.controls}>
        {!isRunning ? (
          <Button
            testID="timer-start"
            label="Start"
            size="large"
            onPress={() => void handleStart()}
            accessibilityHint="Starts recording verified study time"
          />
        ) : (
          <>
            {timer.state.status === 'active' ? (
              <Button
                testID="timer-pause"
                label="Pause"
                size="large"
                variant="secondary"
                onPress={() => void timer.pause()}
              />
            ) : (
              <Button
                testID="timer-resume"
                label="Resume"
                size="large"
                onPress={() => void timer.resume()}
              />
            )}
            <Button
              testID="timer-stop"
              label="Stop"
              size="large"
              variant="danger"
              onPress={() => void handleStop()}
              accessibilityHint="Ends the session and saves your study time"
            />
          </>
        )}
      </View>

      {/* Subject picker — hidden mid-session so time cannot be reattributed. */}
      {!isRunning ? (
        <Card testID="timer-subject-picker">
          <Text variant="heading">Subject</Text>
          {subjects.data?.map((subject) => {
            const selected = (selectedSubjectId ?? subjects.data?.[0]?.id) === subject.id;
            return (
              <Button
                key={subject.id}
                label={subject.name}
                variant={selected ? 'primary' : 'ghost'}
                onPress={() => setSelectedSubjectId(subject.id)}
                accessibilityHint={selected ? 'Currently selected' : 'Select this subject'}
              />
            );
          })}
        </Card>
      ) : null}

      {sync.pending > 0 ? (
        <Card testID="timer-pending">
          <Text variant="caption" color="secondary">
            {sync.pending} session{sync.pending === 1 ? '' : 's'} waiting to sync.
            {sync.isSyncing ? ' Syncing now…' : ' They will upload automatically.'}
          </Text>
        </Card>
      ) : null}

      {timer.state.intervalCount > 0 ? (
        <Card>
          <Text variant="caption" color="secondary">
            {timer.state.intervalCount} focus block
            {timer.state.intervalCount === 1 ? '' : 's'} ·{' '}
            {formatDurationLong(timer.state.elapsedSeconds)} recorded
          </Text>
        </Card>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.lg },
  controls: { gap: spacing.md },
});
