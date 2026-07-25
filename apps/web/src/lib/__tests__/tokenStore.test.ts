/**
 * The browser store deliberately holds less than it used to.
 *
 * These assertions exist to stop a future change quietly reintroducing persistence: the
 * access token must stay in memory, the refresh token must never be readable here at all,
 * and neither may end up in `localStorage`, where any injected script could read them.
 */

import { afterEach, describe, expect, it } from 'vitest';

import { webTokenStore } from '../tokenStore';

const tokenPair = {
  access_token: 'access-123',
  refresh_token: 'refresh-456',
  token_type: 'Bearer',
  expires_in: 900,
};

describe('webTokenStore', () => {
  afterEach(async () => {
    await webTokenStore.clear();
    window.localStorage.clear();
  });

  it('starts empty', async () => {
    expect(await webTokenStore.getAccessToken()).toBeNull();
    expect(await webTokenStore.getRefreshToken()).toBeNull();
  });

  it('keeps the access token in memory', async () => {
    await webTokenStore.setTokens(tokenPair);
    expect(await webTokenStore.getAccessToken()).toBe('access-123');
  });

  it('never exposes a refresh token, even when the server sends one', async () => {
    await webTokenStore.setTokens(tokenPair);
    // The browser's refresh token lives in an httpOnly cookie. Returning anything here
    // would mean a copy existed somewhere JavaScript can reach.
    expect(await webTokenStore.getRefreshToken()).toBeNull();
  });

  it('writes nothing to localStorage', async () => {
    await webTokenStore.setTokens(tokenPair);
    expect(window.localStorage.length).toBe(0);
  });

  it('clears the access token', async () => {
    await webTokenStore.setTokens(tokenPair);
    await webTokenStore.clear();
    expect(await webTokenStore.getAccessToken()).toBeNull();
  });

  it('does not survive a reload', async () => {
    await webTokenStore.setTokens(tokenPair);
    // Nothing is persisted, so a fresh page load starts signed out and recovers the session
    // by refreshing against the cookie — that is the trade this design makes.
    expect(window.localStorage.getItem('sl_access_token')).toBeNull();
    expect(window.localStorage.getItem('sl_refresh_token')).toBeNull();
  });
});
