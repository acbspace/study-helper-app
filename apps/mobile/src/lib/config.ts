/**
 * Runtime configuration.
 *
 * Reads `EXPO_PUBLIC_API_BASE_URL` first (per-developer override), then the value baked
 * into app.json. Android emulators cannot reach `localhost` on the host machine, so the
 * default is corrected for that platform rather than silently failing to connect.
 */

import Constants from 'expo-constants';
import { Platform } from 'react-native';

const DEFAULT_PORT = 8000;

function defaultBaseUrl(): string {
  const host = Platform.OS === 'android' ? '10.0.2.2' : 'localhost';
  return `http://${host}:${DEFAULT_PORT}/api/v1`;
}

function resolveBaseUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_BASE_URL;
  if (fromEnv) return fromEnv;

  const fromManifest = Constants.expoConfig?.extra?.apiBaseUrl as string | undefined;
  if (fromManifest && Platform.OS !== 'android') return fromManifest;

  return defaultBaseUrl();
}

export const config = {
  apiBaseUrl: resolveBaseUrl(),
  /** Display refresh cadence for the running timer. */
  timerTickMs: 1000,
  /** How often the app retries the outbox while it has pending sessions. */
  syncRetryMs: 30_000,
} as const;
