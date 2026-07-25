import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { Tabs, useRouter } from 'expo-router';

import { minTouchTarget, radius, spacing } from '@study-league/design-tokens';

import { Text } from '@/components/Text';
import { useUnreadNotificationCount } from '@/features/api/queries';
import { usePushRegistration } from '@/features/notifications/usePushRegistration';
import { useStudyPresence } from '@/features/presence/useStudyPresence';
import { useRealtime } from '@/features/realtime/useRealtime';
import { useTheme } from '@/theme/ThemeProvider';

/**
 * Main tabs. Friends and Groups are live (M2); League remains a placeholder for M3 so the
 * information architecture is stable from the first release — users should not have to
 * relearn the app when it ships.
 */
export default function TabsLayout(): React.ReactElement {
  const { theme } = useTheme();
  // Broadcast presence from the timer, and keep a socket open for live updates, for as long
  // as the authenticated tabs are mounted.
  useStudyPresence();
  useRealtime();
  // Register for push once, now that we know the user is signed in.
  usePushRegistration();
  const unread = useUnreadNotificationCount();
  const unreadCount = unread.data?.unread ?? 0;

  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: theme.background },
        headerTintColor: theme.textPrimary,
        tabBarStyle: { backgroundColor: theme.surface, borderTopColor: theme.border },
        tabBarActiveTintColor: theme.accent,
        tabBarInactiveTintColor: theme.textSecondary,
        sceneStyle: { backgroundColor: theme.background },
        // In the header rather than as a seventh tab: the tab bar is the app's primary
        // navigation and adding an inbox to it would demote a study surface to make room.
        headerRight: () => <NotificationsBell unread={unreadCount} />,
      }}
    >
      <Tabs.Screen name="today" options={{ title: 'Today' }} />
      <Tabs.Screen name="timer" options={{ title: 'Timer' }} />
      <Tabs.Screen name="insights" options={{ title: 'Insights' }} />
      <Tabs.Screen name="friends" options={{ title: 'Friends' }} />
      <Tabs.Screen name="groups" options={{ title: 'Groups' }} />
      <Tabs.Screen name="league" options={{ title: 'League' }} />
    </Tabs>
  );
}

/**
 * Header entry point to the inbox, with the unread count spoken as part of the label so a
 * screen-reader user hears "Notifications, 3 unread" rather than an unexplained number.
 */
function NotificationsBell({ unread }: { unread: number }): React.ReactElement {
  const { theme } = useTheme();
  const router = useRouter();
  const label = unread > 99 ? '99+' : String(unread);

  return (
    <Pressable
      testID="open-notifications"
      onPress={() => router.push('/notifications')}
      accessibilityRole="button"
      accessibilityLabel={
        unread > 0 ? `Notifications, ${unread} unread` : 'Notifications, none unread'
      }
      style={styles.bell}
    >
      <Text variant="label" color="accent">
        Alerts
      </Text>
      {unread > 0 ? (
        <View
          testID="notifications-badge"
          style={[styles.badge, { backgroundColor: theme.accent }]}
        >
          <Text variant="caption" color="inverse">
            {label}
          </Text>
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  bell: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    minHeight: minTouchTarget,
    paddingHorizontal: spacing.md,
  },
  badge: {
    minWidth: 22,
    paddingHorizontal: spacing.xs,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
