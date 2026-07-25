import React from 'react';

import { Tabs } from 'expo-router';

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

  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: theme.background },
        headerTintColor: theme.textPrimary,
        tabBarStyle: { backgroundColor: theme.surface, borderTopColor: theme.border },
        tabBarActiveTintColor: theme.accent,
        tabBarInactiveTintColor: theme.textSecondary,
        sceneStyle: { backgroundColor: theme.background },
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
