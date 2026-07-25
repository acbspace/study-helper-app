/**
 * The in-app notification inbox.
 *
 * The server has produced durable notifications since M2 — friend requests, group invites,
 * league results — and nothing in the app ever read them. This is where they surface.
 *
 * Read state is a server concern (it drives the unread badge and the push worker), so tapping
 * a row marks it read remotely rather than only locally.
 */

import React from 'react';
import { RefreshControl, ScrollView, StyleSheet, View } from 'react-native';

import type { NotificationKind } from '@study-league/api-client';
import { spacing } from '@study-league/design-tokens';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { EmptyState, ErrorState, LoadingState } from '@/components/StateViews';
import { Text } from '@/components/Text';
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from '@/features/api/queries';
import { useTheme } from '@/theme/ThemeProvider';

/** A short label per kind, so a glance down the list is scannable. */
const KIND_LABELS: Record<NotificationKind, string> = {
  friend_request: 'Friends',
  group_invite: 'Groups',
  session_flagged: 'Integrity',
  league_promoted: 'League',
  league_relegated: 'League',
  mission_completed: 'League',
  encouragement: 'Encouragement',
};

export function NotificationsScreen(): React.ReactElement {
  const { theme } = useTheme();
  const notifications = useNotifications();
  const markRead = useMarkNotificationRead();
  const markAllRead = useMarkAllNotificationsRead();

  if (notifications.isLoading && !notifications.data) {
    return <LoadingState label="Loading notifications…" />;
  }
  if (notifications.isError && !notifications.data) {
    return <ErrorState onRetry={() => void notifications.refetch()} />;
  }

  const rows = notifications.data ?? [];
  const unread = rows.filter((row) => row.read_at === null);

  return (
    <ScrollView
      testID="notifications-screen"
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl
          refreshing={notifications.isFetching}
          onRefresh={() => void notifications.refetch()}
        />
      }
    >
      {unread.length > 0 ? (
        <Button
          testID="notifications-mark-all"
          label={`Mark all read (${unread.length})`}
          variant="secondary"
          onPress={() => markAllRead.mutate()}
          loading={markAllRead.isPending}
        />
      ) : null}

      {rows.length === 0 ? (
        <EmptyState
          testID="notifications-empty"
          title="Nothing new"
          description="Friend requests, group invites, and league results will show up here."
        />
      ) : (
        rows.map((notification) => (
          <Card
            key={notification.id}
            testID={`notification-${notification.id}`}
            style={
              notification.read_at === null
                ? { borderColor: theme.accent, borderLeftWidth: 3 }
                : undefined
            }
          >
            <View style={styles.header}>
              <Text variant="caption" color="accent">
                {KIND_LABELS[notification.kind] ?? 'Update'}
              </Text>
              <Text variant="caption" color="secondary">
                {formatWhen(notification.created_at)}
              </Text>
            </View>

            <Text variant="label">{notification.title}</Text>
            <Text variant="body" color="secondary">
              {notification.body}
            </Text>

            {notification.read_at === null ? (
              <Button
                testID={`notification-read-${notification.id}`}
                label="Mark read"
                variant="ghost"
                onPress={() => markRead.mutate(notification.id)}
                accessibilityHint={`Marks "${notification.title}" as read.`}
              />
            ) : null}
          </Card>
        ))
      )}
    </ScrollView>
  );
}

/**
 * Relative time, coarse on purpose: "3 days ago" is what a user wants from an inbox, and it
 * avoids a date-format library plus a locale decision for a single line of text.
 */
export function formatWhen(isoTimestamp: string, now: Date = new Date()): string {
  const then = new Date(isoTimestamp);
  const seconds = Math.max(0, Math.floor((now.getTime() - then.getTime()) / 1000));

  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return then.toLocaleDateString();
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.md },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
});
