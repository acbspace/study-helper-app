/**
 * Browser token storage for the API client.
 *
 * The access token lives in memory only and the refresh token is never held here at all —
 * the server keeps it in an httpOnly cookie the page cannot read. `localStorage` was the
 * obvious place for both and the wrong one: anything a page's own JavaScript can read,
 * injected JavaScript can exfiltrate, and a 30-day refresh token read out of storage is a
 * month of silent account access.
 *
 * The cost is that a reload starts with no access token. That is fine — the client refreshes
 * against the cookie on the first 401 and the session continues, which is exactly the
 * exchange this design is making: one extra round trip after a reload, in return for a
 * credential XSS cannot reach.
 */

import type { AuthTokens, TokenStore } from '@study-league/api-client';

let accessToken: string | null = null;

export const webTokenStore: TokenStore = {
  async getAccessToken(): Promise<string | null> {
    return accessToken;
  },
  async getRefreshToken(): Promise<string | null> {
    // Always null by design; the cookie is sent by the browser, not by this code.
    return null;
  },
  async setTokens(tokens: AuthTokens): Promise<void> {
    accessToken = tokens.access_token;
  },
  async clear(): Promise<void> {
    accessToken = null;
  },
};

/** Test seam: lets a test start from a known signed-in state. */
export function __setAccessTokenForTests(token: string | null): void {
  accessToken = token;
}
