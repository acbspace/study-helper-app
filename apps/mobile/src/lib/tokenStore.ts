/**
 * Token storage backed by the device keychain/keystore.
 *
 * Tokens never touch AsyncStorage: that is plain text on disk and readable on a rooted or
 * jailbroken device. SecureStore is hardware-backed where available.
 */

import * as SecureStore from 'expo-secure-store';

import type { AuthTokens, TokenStore } from '@study-league/api-client';

const ACCESS_KEY = 'sl.access_token';
const REFRESH_KEY = 'sl.refresh_token';

export const secureTokenStore: TokenStore = {
  async getAccessToken() {
    return SecureStore.getItemAsync(ACCESS_KEY);
  },

  async getRefreshToken() {
    return SecureStore.getItemAsync(REFRESH_KEY);
  },

  async setTokens(tokens: AuthTokens) {
    await SecureStore.setItemAsync(ACCESS_KEY, tokens.access_token);
    await SecureStore.setItemAsync(REFRESH_KEY, tokens.refresh_token);
  },

  async clear() {
    await SecureStore.deleteItemAsync(ACCESS_KEY);
    await SecureStore.deleteItemAsync(REFRESH_KEY);
  },
};

const DEVICE_ID_KEY = 'sl.device_id';

/**
 * Stable per-installation identifier.
 *
 * Generated locally and sent as `X-Device-Id`; the server stores only a salted hash, so
 * this identifies an installation for integrity checks without being a tracking handle.
 */
export async function getOrCreateDeviceId(generate: () => string): Promise<string> {
  const existing = await SecureStore.getItemAsync(DEVICE_ID_KEY);
  if (existing) return existing;
  const created = generate();
  await SecureStore.setItemAsync(DEVICE_ID_KEY, created);
  return created;
}
