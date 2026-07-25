/**
 * Loading, empty, error, and offline states.
 *
 * Every data-driven screen renders one of these rather than a blank space, so the app
 * always explains itself — including when the network is gone, which for a study timer is
 * a normal condition rather than a failure.
 */

import React from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { spacing } from '@study-league/design-tokens';

import { useTheme } from '@/theme/ThemeProvider';

import { Button } from './Button';
import { Text } from './Text';

export function LoadingState({ label = 'Loading…' }: { label?: string }): React.ReactElement {
  const { theme } = useTheme();
  return (
    <View style={styles.container} accessibilityRole="progressbar" accessibilityLabel={label}>
      <ActivityIndicator color={theme.accent} />
      <Text variant="label" color="secondary">
        {label}
      </Text>
    </View>
  );
}

export function EmptyState({
  title,
  description,
  actionLabel,
  onAction,
  testID,
}: {
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  testID?: string;
}): React.ReactElement {
  return (
    <View style={styles.container} testID={testID}>
      <Text variant="heading" align="center">
        {title}
      </Text>
      {description ? (
        <Text variant="body" color="secondary" align="center">
          {description}
        </Text>
      ) : null}
      {actionLabel && onAction ? (
        <Button label={actionLabel} onPress={onAction} variant="secondary" />
      ) : null}
    </View>
  );
}

export function ErrorState({
  title = 'Something went wrong',
  description,
  onRetry,
  testID,
}: {
  title?: string;
  description?: string;
  onRetry?: () => void;
  testID?: string;
}): React.ReactElement {
  return (
    <View style={styles.container} testID={testID}>
      <Text variant="heading" align="center" color="danger">
        {title}
      </Text>
      {description ? (
        <Text variant="body" color="secondary" align="center">
          {description}
        </Text>
      ) : null}
      {onRetry ? <Button label="Try again" onPress={onRetry} variant="secondary" /> : null}
    </View>
  );
}

export function OfflineNotice({
  pendingCount = 0,
  testID,
}: {
  pendingCount?: number;
  testID?: string;
}): React.ReactElement {
  const { theme } = useTheme();
  const message =
    pendingCount > 0
      ? `Offline — ${pendingCount} session${pendingCount === 1 ? '' : 's'} will sync automatically.`
      : 'Offline — your timer still works and will sync later.';

  return (
    <View
      testID={testID}
      accessibilityRole="alert"
      style={[styles.banner, { backgroundColor: theme.surfaceMuted, borderColor: theme.border }]}
    >
      <Text variant="caption" color="secondary">
        {message}
      </Text>
    </View>
  );
}

/**
 * Shown where a platform capability is unavailable (e.g. app blocking on iOS).
 * Unsupported features are labelled honestly rather than presented as working.
 */
export function UnsupportedFeatureNotice({
  feature,
  reason,
}: {
  feature: string;
  reason: string;
}): React.ReactElement {
  const { theme } = useTheme();
  return (
    <View
      style={[styles.banner, { backgroundColor: theme.surfaceMuted, borderColor: theme.border }]}
    >
      <Text variant="label">{feature} is not available on this device</Text>
      <Text variant="caption" color="secondary">
        {reason}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.md,
    padding: spacing.xl,
  },
  banner: {
    borderRadius: 10,
    borderWidth: 1,
    padding: spacing.md,
    gap: spacing.xxs,
  },
});
