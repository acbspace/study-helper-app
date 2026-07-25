/**
 * Browser token storage for the API client.
 *
 * Tokens live in `localStorage` so a refresh keeps the session; the API client owns rotation.
 * The interface is async to match the shared `TokenStore` contract (native uses secure async
 * storage), even though the web reads are synchronous underneath.
 */

import type { AuthTokens, TokenStore } from '@study-league/api-client';

const ACCESS_KEY = 'sl_access_token';
const REFRESH_KEY = 'sl_refresh_token';

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null; // private mode / storage disabled — treat as signed out
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Nothing durable to do; the session simply won't survive a reload.
  }
}

export const webTokenStore: TokenStore = {
  async getAccessToken(): Promise<string | null> {
    return read(ACCESS_KEY);
  },
  async getRefreshToken(): Promise<string | null> {
    return read(REFRESH_KEY);
  },
  async setTokens(tokens: AuthTokens): Promise<void> {
    write(ACCESS_KEY, tokens.access_token);
    write(REFRESH_KEY, tokens.refresh_token);
  },
  async clear(): Promise<void> {
    try {
      window.localStorage.removeItem(ACCESS_KEY);
      window.localStorage.removeItem(REFRESH_KEY);
    } catch {
      // no-op
    }
  },
};
