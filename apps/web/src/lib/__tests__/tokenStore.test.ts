import { afterEach, describe, expect, it } from 'vitest';

import { webTokenStore } from '../tokenStore';

describe('webTokenStore', () => {
  afterEach(() => window.localStorage.clear());

  it('starts empty', async () => {
    expect(await webTokenStore.getAccessToken()).toBeNull();
    expect(await webTokenStore.getRefreshToken()).toBeNull();
  });

  it('round-trips a token pair', async () => {
    await webTokenStore.setTokens({
      access_token: 'access-123',
      refresh_token: 'refresh-456',
      token_type: 'Bearer',
      expires_in: 900,
    });
    expect(await webTokenStore.getAccessToken()).toBe('access-123');
    expect(await webTokenStore.getRefreshToken()).toBe('refresh-456');
  });

  it('clears both tokens', async () => {
    await webTokenStore.setTokens({
      access_token: 'a',
      refresh_token: 'b',
      token_type: 'Bearer',
      expires_in: 900,
    });
    await webTokenStore.clear();
    expect(await webTokenStore.getAccessToken()).toBeNull();
    expect(await webTokenStore.getRefreshToken()).toBeNull();
  });
});
