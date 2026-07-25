/**
 * Root layout: providers and the authenticated/unauthenticated routing gate.
 */

import React, { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Stack, useRouter, useSegments } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { LoadingState } from '@/components/StateViews';
import { AuthProvider, useAuth } from '@/features/auth/AuthProvider';
import { useTimerStore } from '@/features/timer/timerStore';
import { ThemeProvider, useTheme } from '@/theme/ThemeProvider';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // A failed refetch must not blank out data the user can still read offline.
      refetchOnWindowFocus: false,
      retry: 2,
    },
  },
});

function RootNavigator(): React.ReactElement {
  const { status } = useAuth();
  const { theme } = useTheme();
  const segments = useSegments();
  const router = useRouter();
  const hydrate = useTimerStore((state) => state.hydrate);

  // Restore any running timer as early as possible, before the user reaches a screen.
  useEffect(() => {
    void hydrate();
  }, [hydrate]);

  useEffect(() => {
    if (status === 'loading') return;
    const inAuthGroup = segments[0] === '(auth)';

    if (status === 'unauthenticated' && !inAuthGroup) {
      router.replace('/(auth)/sign-in');
    } else if (status === 'authenticated' && inAuthGroup) {
      router.replace('/(tabs)/today');
    }
  }, [status, segments, router]);

  if (status === 'loading') {
    return (
      <View style={[styles.loading, { backgroundColor: theme.background }]}>
        <LoadingState label="Starting Study League…" />
      </View>
    );
  }

  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: theme.background },
        headerTintColor: theme.textPrimary,
        contentStyle: { backgroundColor: theme.background },
      }}
    >
      <Stack.Screen name="(auth)" options={{ headerShown: false }} />
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      <Stack.Screen name="subjects" options={{ title: 'Subjects', presentation: 'modal' }} />
      <Stack.Screen name="goals" options={{ title: 'Goals' }} />
      <Stack.Screen name="community" options={{ title: 'Community' }} />
    </Stack>
  );
}

export default function RootLayout(): React.ReactElement {
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <StatusBar style="auto" />
            <RootNavigator />
          </AuthProvider>
        </QueryClientProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});
