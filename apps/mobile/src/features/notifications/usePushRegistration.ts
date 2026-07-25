/**
 * Register this installation for push, once per sign-in.
 *
 * Until this existed the whole push path was dead: the server had `PUT /me/push-token` and
 * the worker polled for pending notifications every two minutes, but no client ever supplied
 * a token, so there was never anything to deliver to.
 *
 * Failure here is deliberately quiet. A user who declines the permission prompt, or an
 * emulator with no push support, should still have a fully working app — push is an
 * accelerator for the in-app inbox, never the only way a notification arrives.
 */

import { useEffect, useRef } from 'react';
import { Platform } from 'react-native';

import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';

import { useAuth } from '@/features/auth/AuthProvider';
import type { PushPlatform } from '@study-league/api-client';

function devicePlatform(): PushPlatform {
  if (Platform.OS === 'ios') return 'ios';
  if (Platform.OS === 'android') return 'android';
  if (Platform.OS === 'web') return 'web';
  return 'unknown';
}

/**
 * Ask for permission and hand the resulting Expo token to the server.
 *
 * Returns nothing: callers cannot act on the outcome, and treating a declined permission as
 * an error would push every screen into handling something that is a normal user choice.
 */
export async function registerForPush(
  register: (token: string, platform: PushPlatform) => Promise<void>,
  notificationsEnabled: boolean,
): Promise<void> {
  // The user's own setting wins over the OS permission: someone who turned notifications
  // off in the app has not consented to a token being stored server-side either.
  if (!notificationsEnabled) return;
  // A simulator cannot receive push, and asking for the permission there trains users to
  // dismiss a prompt that could not have worked.
  if (!Device.isDevice) return;

  try {
    const existing = await Notifications.getPermissionsAsync();
    let granted = existing.granted;
    if (!granted && existing.canAskAgain) {
      granted = (await Notifications.requestPermissionsAsync()).granted;
    }
    if (!granted) return;

    const token = await Notifications.getExpoPushTokenAsync();
    await register(token.data, devicePlatform());
  } catch {
    // Offline, no project id, provider unreachable: the inbox still works.
  }
}

/** Run the registration once the user is signed in, and once per session only. */
export function usePushRegistration(): void {
  const { client, status, user } = useAuth();
  const attempted = useRef(false);

  useEffect(() => {
    if (status !== 'authenticated' || !user) return;
    if (attempted.current) return;
    attempted.current = true;

    void registerForPush(
      (token, platform) => client.registerPushToken(token, platform),
      user.settings.notifications_enabled,
    );
  }, [client, status, user]);
}
