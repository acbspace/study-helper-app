/**
 * Settings: profile, study configuration, privacy, and account actions.
 *
 * Every field here already existed in the database and drove real behaviour — scheduled
 * study days feed the league's consistency score, the privacy switches decide what presence
 * reveals — but nothing in the app could change any of them, so every account ran on its
 * registration defaults forever. This screen is what makes those columns reachable.
 *
 * Settings writes carry `expected_version`, so two devices editing at once produce an
 * explicit conflict the user can resolve rather than a silent last-write-wins.
 */

import React, { useState } from 'react';
import { ScrollView, StyleSheet, Switch, TextInput, View } from 'react-native';

import { ApiError } from '@study-league/api-client';
import { minTouchTarget, radius, spacing } from '@study-league/design-tokens';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { EmptyState, LoadingState } from '@/components/StateViews';
import { Text } from '@/components/Text';
import {
  useBlockedUsers,
  useUnblockUser,
  useUpdateProfile,
  useUpdateSettings,
} from '@/features/api/queries';
import { resolveDeviceTimezone, useAuth } from '@/features/auth/AuthProvider';
import { useTheme } from '@/theme/ThemeProvider';

/** Monday = bit 0 … Sunday = bit 6, matching `user_settings.scheduled_study_days`. */
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const;

export function SettingsScreen(): React.ReactElement {
  const { user, signOut, client } = useAuth();
  const updateSettings = useUpdateSettings();
  const updateProfile = useUpdateProfile();
  const blocked = useBlockedUsers();
  const unblock = useUnblockUser();

  const [displayName, setDisplayName] = useState(user?.profile.display_name ?? '');
  const [bio, setBio] = useState(user?.profile.bio ?? '');
  const [timezone, setTimezone] = useState(user?.settings.timezone ?? 'UTC');
  const [dailyGoal, setDailyGoal] = useState(String(user?.settings.daily_goal_minutes ?? 0));
  const [weeklyGoal, setWeeklyGoal] = useState(String(user?.settings.weekly_goal_minutes ?? 0));
  const [focusMinutes, setFocusMinutes] = useState(
    String(user?.settings.pomodoro_focus_minutes ?? 25),
  );
  const [breakMinutes, setBreakMinutes] = useState(
    String(user?.settings.pomodoro_break_minutes ?? 5),
  );
  const [exportState, setExportState] = useState<'idle' | 'working' | 'done' | 'failed'>('idle');

  if (!user) return <LoadingState label="Loading your settings…" />;

  const settings = user.settings;

  /**
   * Toggles are saved immediately — a switch that needs a separate "save" is a switch users
   * think they already set. Text and number fields wait for an explicit save instead, so a
   * half-typed value is never sent.
   */
  const save = (changes: Parameters<typeof updateSettings.mutate>[0]) => {
    updateSettings.mutate({ ...changes, expected_version: settings.version });
  };

  const toggleDay = (index: number) => {
    save({ scheduled_study_days: settings.scheduled_study_days ^ (1 << index) });
  };

  const saveGoals = () => {
    save({
      daily_goal_minutes: clampInt(dailyGoal, 0, 1440, settings.daily_goal_minutes),
      weekly_goal_minutes: clampInt(weeklyGoal, 0, 10080, settings.weekly_goal_minutes),
    });
  };

  const savePomodoro = () => {
    save({
      pomodoro_focus_minutes: clampInt(focusMinutes, 1, 180, settings.pomodoro_focus_minutes),
      pomodoro_break_minutes: clampInt(breakMinutes, 1, 60, settings.pomodoro_break_minutes),
    });
  };

  const handleExport = async () => {
    setExportState('working');
    try {
      await client.exportMyData();
      setExportState('done');
    } catch {
      setExportState('failed');
    }
  };

  const scheduledCount = WEEKDAYS.filter(
    (_day, index) => (settings.scheduled_study_days & (1 << index)) !== 0,
  ).length;

  return (
    <ScrollView testID="settings-screen" contentContainerStyle={styles.content}>
      {updateSettings.isError ? (
        <Text variant="caption" color="danger" accessibilityRole="alert" testID="settings-error">
          {describeError(updateSettings.error)}
        </Text>
      ) : null}

      {/* Profile */}
      <Card testID="settings-profile">
        <Text variant="heading">Profile</Text>
        <Text variant="caption" color="secondary">
          Signed in as {user.email} · @{user.profile.username}
        </Text>

        <Field label="Display name">
          <Input
            testID="settings-display-name"
            value={displayName}
            onChangeText={setDisplayName}
            maxLength={50}
            accessibilityLabel="Display name"
          />
        </Field>

        <Field label="Bio">
          <Input
            testID="settings-bio"
            value={bio}
            onChangeText={setBio}
            maxLength={280}
            multiline
            accessibilityLabel="Bio"
          />
        </Field>

        <Button
          testID="settings-save-profile"
          label="Save profile"
          onPress={() =>
            updateProfile.mutate({ display_name: displayName.trim(), bio: bio.trim() })
          }
          loading={updateProfile.isPending}
          disabled={!displayName.trim()}
        />
        {updateProfile.isError ? (
          <Text variant="caption" color="danger" accessibilityRole="alert">
            {describeError(updateProfile.error)}
          </Text>
        ) : null}
      </Card>

      {/* Scheduled study days — the league's consistency component is measured against these */}
      <Card testID="settings-schedule">
        <Text variant="heading">Study days</Text>
        <Text variant="caption" color="secondary">
          Days you plan to study. Rest days you did not schedule never count against your league
          consistency score.
        </Text>

        <View style={styles.dayRow}>
          {WEEKDAYS.map((day, index) => {
            const selected = (settings.scheduled_study_days & (1 << index)) !== 0;
            return (
              <Button
                key={day}
                testID={`settings-day-${day.toLowerCase()}`}
                label={day}
                variant={selected ? 'primary' : 'ghost'}
                onPress={() => toggleDay(index)}
                accessibilityHint={
                  selected
                    ? `${day} is a scheduled study day. Tap to unschedule.`
                    : `Schedule ${day}.`
                }
                style={styles.dayChip}
              />
            );
          })}
        </View>
        <Text variant="caption" color="secondary" testID="settings-schedule-count">
          {scheduledCount} {scheduledCount === 1 ? 'day' : 'days'} scheduled
        </Text>
      </Card>

      {/* Goals */}
      <Card testID="settings-goals">
        <Text variant="heading">Daily and weekly goals</Text>
        <Field label="Daily goal (minutes)">
          <Input
            testID="settings-daily-goal"
            value={dailyGoal}
            onChangeText={setDailyGoal}
            keyboardType="number-pad"
            accessibilityLabel="Daily goal in minutes"
          />
        </Field>
        <Field label="Weekly goal (minutes)">
          <Input
            testID="settings-weekly-goal"
            value={weeklyGoal}
            onChangeText={setWeeklyGoal}
            keyboardType="number-pad"
            accessibilityLabel="Weekly goal in minutes"
          />
        </Field>
        <Button
          testID="settings-save-goals"
          label="Save goals"
          onPress={saveGoals}
          loading={updateSettings.isPending}
        />
      </Card>

      {/* Pomodoro */}
      <Card testID="settings-pomodoro">
        <Text variant="heading">Pomodoro</Text>
        <Field label="Focus (minutes)">
          <Input
            testID="settings-focus-minutes"
            value={focusMinutes}
            onChangeText={setFocusMinutes}
            keyboardType="number-pad"
            accessibilityLabel="Pomodoro focus minutes"
          />
        </Field>
        <Field label="Break (minutes)">
          <Input
            testID="settings-break-minutes"
            value={breakMinutes}
            onChangeText={setBreakMinutes}
            keyboardType="number-pad"
            accessibilityLabel="Pomodoro break minutes"
          />
        </Field>
        <Button
          testID="settings-save-pomodoro"
          label="Save pomodoro"
          onPress={savePomodoro}
          loading={updateSettings.isPending}
        />
      </Card>

      {/* Time zone */}
      <Card testID="settings-timezone">
        <Text variant="heading">Time zone</Text>
        <Text variant="caption" color="secondary">
          Every statistic — day boundaries, streaks, the shape of your week — is computed in this
          zone.
        </Text>
        <Input
          testID="settings-timezone-input"
          value={timezone}
          onChangeText={setTimezone}
          autoCapitalize="none"
          autoCorrect={false}
          maxLength={64}
          accessibilityLabel="Time zone"
        />
        <View style={styles.buttonRow}>
          <Button
            testID="settings-use-device-timezone"
            label="Use this device's zone"
            variant="ghost"
            onPress={() => setTimezone(resolveDeviceTimezone())}
            style={styles.flex}
          />
          <Button
            testID="settings-save-timezone"
            label="Save"
            onPress={() => save({ timezone: timezone.trim() })}
            loading={updateSettings.isPending}
            disabled={!timezone.trim()}
            style={styles.flex}
          />
        </View>
      </Card>

      {/* Privacy */}
      <Card testID="settings-privacy">
        <Text variant="heading">Privacy</Text>
        <Toggle
          testID="settings-show-presence"
          label="Show when I'm studying"
          description="Friends and group members can see that you are in a session. Turning this off stops your presence being stored at all."
          value={settings.privacy_show_presence}
          onValueChange={(value) => save({ privacy_show_presence: value })}
        />
        <Toggle
          testID="settings-show-subject"
          label="Show what I'm studying"
          description="Includes the subject name alongside your presence."
          value={settings.privacy_show_subject}
          onValueChange={(value) => save({ privacy_show_subject: value })}
        />
        <Toggle
          testID="settings-notifications"
          label="Notifications"
          description="Friend requests, group invitations, and league results."
          value={settings.notifications_enabled}
          onValueChange={(value) => save({ notifications_enabled: value })}
        />
      </Card>

      {/* Blocked users */}
      <Card testID="settings-blocked">
        <Text variant="heading">Blocked</Text>
        {blocked.isLoading && !blocked.data ? (
          <LoadingState label="Loading blocked users…" />
        ) : (blocked.data?.length ?? 0) === 0 ? (
          <EmptyState
            testID="settings-blocked-empty"
            title="Nobody is blocked"
            description="Blocked people cannot find you, and never see that they were blocked."
          />
        ) : (
          blocked.data?.map((person) => (
            <View key={person.id} style={styles.personRow}>
              <Text variant="body" style={styles.flex}>
                {person.display_name}
              </Text>
              <Button
                label="Unblock"
                variant="ghost"
                onPress={() => unblock.mutate(person.id)}
                accessibilityHint={`Unblocks ${person.display_name}.`}
              />
            </View>
          ))
        )}
      </Card>

      {/* Account */}
      <Card testID="settings-account">
        <Text variant="heading">Your data</Text>
        <Text variant="caption" color="secondary">
          A portable copy of everything you have created.
        </Text>
        <Button
          testID="settings-export"
          label={exportState === 'done' ? 'Export ready' : 'Export my data'}
          variant="secondary"
          loading={exportState === 'working'}
          onPress={() => void handleExport()}
        />
        {exportState === 'failed' ? (
          <Text variant="caption" color="danger" accessibilityRole="alert">
            Could not build the export. Check your connection and try again.
          </Text>
        ) : null}

        <Button
          testID="settings-sign-out"
          label="Sign out"
          variant="danger"
          onPress={() => void signOut()}
          accessibilityHint="Signs out and clears this device's local study data."
        />
      </Card>
    </ScrollView>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <View style={styles.field}>
      <Text variant="label">{label}</Text>
      {children}
    </View>
  );
}

function Input(props: React.ComponentProps<typeof TextInput>): React.ReactElement {
  const { theme, fontSize } = useTheme();
  return (
    <TextInput
      placeholderTextColor={theme.textSecondary}
      {...props}
      style={[
        {
          minHeight: minTouchTarget,
          borderRadius: radius.md,
          borderWidth: 1,
          borderColor: theme.border,
          backgroundColor: theme.surfaceMuted,
          color: theme.textPrimary,
          paddingHorizontal: spacing.md,
          fontSize: fontSize('body'),
        },
        props.style,
      ]}
    />
  );
}

function Toggle({
  label,
  description,
  value,
  onValueChange,
  testID,
}: {
  label: string;
  description: string;
  value: boolean;
  onValueChange: (value: boolean) => void;
  testID: string;
}): React.ReactElement {
  const { theme } = useTheme();
  return (
    <View style={styles.toggleRow}>
      <View style={styles.flex}>
        <Text variant="body">{label}</Text>
        <Text variant="caption" color="secondary">
          {description}
        </Text>
      </View>
      <Switch
        testID={testID}
        value={value}
        onValueChange={onValueChange}
        accessibilityLabel={label}
        trackColor={{ false: theme.border, true: theme.accent }}
      />
    </View>
  );
}

/** Keep an unparseable or out-of-range entry from being sent as a rejected write. */
function clampInt(raw: string, min: number, max: number, fallback: number): number {
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed)) return fallback;
  return Math.min(Math.max(parsed, min), max);
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'version_conflict') {
      return 'These settings were changed on another device. Reopen this screen to see the current values.';
    }
    if (error.code === 'network_error') {
      return 'Could not reach the server. Your settings were not changed.';
    }
    return error.message;
  }
  return 'Could not save. Please try again.';
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.lg },
  field: { gap: spacing.xs },
  dayRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  dayChip: { flexGrow: 1, paddingHorizontal: spacing.sm },
  buttonRow: { flexDirection: 'row', gap: spacing.sm },
  personRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  toggleRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  flex: { flex: 1 },
});
