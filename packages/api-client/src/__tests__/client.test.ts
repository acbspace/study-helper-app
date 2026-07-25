/**
 * ApiClient transport behaviour: auth attachment, refresh-on-401, error mapping, and
 * idempotency headers. Uses a fake fetch so no server is required.
 */

import { describe, expect, it, type Mock, vi } from 'vitest';

import { ApiClient, type TokenStore } from '../client';
import { ApiError } from '../errors';

function memoryTokenStore(initial?: {
  access?: string;
  refresh?: string;
}): TokenStore & { access: string | null; refresh: string | null } {
  const store = {
    access: initial?.access ?? null,
    refresh: initial?.refresh ?? null,
    async getAccessToken() {
      return store.access;
    },
    async getRefreshToken() {
      return store.refresh;
    },
    async setTokens(tokens: { access_token: string; refresh_token: string | null }) {
      store.access = tokens.access_token;
      store.refresh = tokens.refresh_token;
    },
    async clear() {
      store.access = null;
      store.refresh = null;
    },
  };
  return store;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** Headers sent on the nth fetch call, with a present-check so types stay strict. */
function headersOfCall(fetchImpl: Mock, index: number): Record<string, string> {
  const call = fetchImpl.mock.calls[index];
  if (!call) throw new Error(`Expected a fetch call at index ${index}`);
  return ((call[1] as RequestInit).headers ?? {}) as Record<string, string>;
}

/** URL and init of the nth fetch call, for assertions about routing and request bodies. */
function requestOfCall(fetchImpl: Mock, index: number): { url: string; init: RequestInit } {
  const call = fetchImpl.mock.calls[index];
  if (!call) throw new Error(`Expected a fetch call at index ${index}`);
  return { url: call[0] as string, init: call[1] as RequestInit };
}

describe('ApiClient', () => {
  it('attaches the bearer token to authenticated requests', async () => {
    const tokens = memoryTokenStore({ access: 'access-1', refresh: 'refresh-1' });
    const fetchImpl = vi.fn(async () => jsonResponse(200, { id: 'u1' }));
    const client = new ApiClient({ baseUrl: 'http://api/api/v1', tokens, fetchImpl });

    await client.getMe();

    expect(headersOfCall(fetchImpl, 0)).toMatchObject({ Authorization: 'Bearer access-1' });
  });

  it('refreshes once on 401 and retries the original request', async () => {
    const tokens = memoryTokenStore({ access: 'expired', refresh: 'refresh-1' });
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { error: { code: 'token_expired', message: 'x' } }))
      .mockResolvedValueOnce(
        jsonResponse(200, { access_token: 'fresh', refresh_token: 'refresh-2', expires_in: 1800 }),
      )
      .mockResolvedValueOnce(jsonResponse(200, { id: 'u1' }));

    const client = new ApiClient({ baseUrl: 'http://api/api/v1', tokens, fetchImpl });
    const me = await client.getMe();

    expect(me).toEqual({ id: 'u1' });
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    // The refreshed token was persisted for future calls.
    expect(tokens.access).toBe('fresh');
  });

  it('gives up and signals auth failure when refresh fails', async () => {
    const tokens = memoryTokenStore({ access: 'expired', refresh: 'bad' });
    const onAuthFailure = vi.fn();
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { error: { code: 'token_expired', message: 'x' } }))
      .mockResolvedValueOnce(
        jsonResponse(401, { error: { code: 'not_authenticated', message: 'x' } }),
      );

    const client = new ApiClient({
      baseUrl: 'http://api/api/v1',
      tokens,
      onAuthFailure,
      fetchImpl,
    });

    await expect(client.getMe()).rejects.toBeInstanceOf(ApiError);
    expect(onAuthFailure).toHaveBeenCalled();
    expect(tokens.access).toBeNull();
  });

  it('maps error envelopes to ApiError with the stable code', async () => {
    const tokens = memoryTokenStore({ access: 'a', refresh: 'r' });
    const fetchImpl = vi.fn(async () =>
      jsonResponse(409, { error: { code: 'active_session_exists', message: 'Already running.' } }),
    );
    const client = new ApiClient({ baseUrl: 'http://api/api/v1', tokens, fetchImpl });

    await expect(client.startSession({ subject_id: 's1' })).rejects.toMatchObject({
      code: 'active_session_exists',
      status: 409,
    });
  });

  it('turns a fetch rejection into a retryable network error', async () => {
    const tokens = memoryTokenStore({ access: 'a', refresh: 'r' });
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('Network request failed');
    });
    const client = new ApiClient({ baseUrl: 'http://api/api/v1', tokens, fetchImpl });

    try {
      await client.getMe();
      throw new Error('should have thrown');
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).code).toBe('network_error');
      expect((error as ApiError).isRetryable).toBe(true);
    }
  });

  it('sends an idempotency key with session sync', async () => {
    const tokens = memoryTokenStore({ access: 'a', refresh: 'r' });
    const fetchImpl = vi.fn(async () => jsonResponse(200, { results: [] }));
    const client = new ApiClient({ baseUrl: 'http://api/api/v1', tokens, fetchImpl });

    await client.syncSessions([], 'key-123');

    expect(headersOfCall(fetchImpl, 0)).toMatchObject({ 'Idempotency-Key': 'key-123' });
  });

  it('refreshes from the cookie when it holds no refresh token', async () => {
    // The browser transport: the token is in an httpOnly cookie this code cannot read, so
    // an empty store must not be mistaken for "signed out".
    const tokens = memoryTokenStore({ access: 'expired' });
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { error: { code: 'token_expired' } }))
      .mockResolvedValueOnce(jsonResponse(200, { access_token: 'fresh', refresh_token: null }))
      .mockResolvedValueOnce(jsonResponse(200, { id: 'u1' }));
    const client = new ApiClient({
      baseUrl: 'http://api/api/v1',
      tokens,
      fetchImpl,
      refreshTransport: 'cookie',
    });

    await client.getMe();

    expect(fetchImpl).toHaveBeenCalledTimes(3);
    const refreshCall = requestOfCall(fetchImpl, 1);
    expect(refreshCall.url).toBe('http://api/api/v1/auth/refresh');
    // No token in the body, and credentials included so the browser attaches the cookie.
    expect(JSON.parse(String(refreshCall.init.body))).toEqual({});
    expect(refreshCall.init.credentials).toBe('include');
    expect(tokens.access).toBe('fresh');
  });

  it('declares the cookie transport on every request', async () => {
    const tokens = memoryTokenStore({ access: 'a' });
    const fetchImpl = vi.fn(async () => jsonResponse(200, { id: 'u1' }));
    const client = new ApiClient({
      baseUrl: 'http://api/api/v1',
      tokens,
      fetchImpl,
      refreshTransport: 'cookie',
    });

    await client.getMe();

    expect(headersOfCall(fetchImpl, 0)).toMatchObject({ 'X-Refresh-Transport': 'cookie' });
  });

  it('leaves body-transport clients sending the token as before', async () => {
    const tokens = memoryTokenStore({ access: 'a', refresh: 'r' });
    const fetchImpl = vi.fn(async () => jsonResponse(200, { id: 'u1' }));
    const client = new ApiClient({ baseUrl: 'http://api/api/v1', tokens, fetchImpl });

    await client.getMe();

    const headers = headersOfCall(fetchImpl, 0);
    expect(headers['X-Refresh-Transport']).toBeUndefined();
    expect(requestOfCall(fetchImpl, 0).init.credentials).toBeUndefined();
  });

  it('gives up when a body-transport client has no refresh token', async () => {
    const tokens = memoryTokenStore({ access: 'expired' });
    const onAuthFailure = vi.fn();
    const fetchImpl = vi.fn(async () => jsonResponse(401, { error: { code: 'token_expired' } }));
    const client = new ApiClient({
      baseUrl: 'http://api/api/v1',
      tokens,
      fetchImpl,
      onAuthFailure,
    });

    await expect(client.getMe()).rejects.toBeInstanceOf(ApiError);
    // One call only: with nothing to refresh with, there is no point attempting it.
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(onAuthFailure).toHaveBeenCalled();
  });

  it('registers a push token against the calling device', async () => {
    const tokens = memoryTokenStore({ access: 'a', refresh: 'r' });
    // The real endpoint answers 204; `Response` refuses a body at that status, and the
    // assertions here are all about the request anyway.
    const fetchImpl = vi.fn(async () => jsonResponse(200, null));
    const client = new ApiClient({
      baseUrl: 'http://api/api/v1',
      tokens,
      fetchImpl,
      deviceId: 'install-7',
    });

    await client.registerPushToken('ExponentPushToken[abc]', 'ios');

    const call = requestOfCall(fetchImpl, 0);
    expect(call.url).toBe('http://api/api/v1/me/push-token');
    expect(call.init.method).toBe('PUT');
    // Without the device header the server rejects the token rather than attaching it to
    // whichever installation registered last.
    expect(headersOfCall(fetchImpl, 0)).toMatchObject({ 'X-Device-Id': 'install-7' });
    expect(JSON.parse(String(call.init.body))).toEqual({
      token: 'ExponentPushToken[abc]',
      platform: 'ios',
    });
  });

  it('passes notification filters as query parameters', async () => {
    const tokens = memoryTokenStore({ access: 'a', refresh: 'r' });
    const fetchImpl = vi.fn(async () => jsonResponse(200, []));
    const client = new ApiClient({ baseUrl: 'http://api/api/v1', tokens, fetchImpl });

    await client.listNotifications({ unreadOnly: true, limit: 20 });

    expect(requestOfCall(fetchImpl, 0).url).toBe(
      'http://api/api/v1/notifications?unread_only=true&limit=20',
    );
  });

  it('files a report', async () => {
    const tokens = memoryTokenStore({ access: 'a', refresh: 'r' });
    const fetchImpl = vi.fn(async () => jsonResponse(201, { id: 'r1' }));
    const client = new ApiClient({ baseUrl: 'http://api/api/v1', tokens, fetchImpl });

    await client.reportContent({ subject_type: 'post', subject_id: 'p1', reason: 'Spam' });

    const call = requestOfCall(fetchImpl, 0);
    expect(call.url).toBe('http://api/api/v1/reports');
    expect(JSON.parse(String(call.init.body))).toEqual({
      subject_type: 'post',
      subject_id: 'p1',
      reason: 'Spam',
    });
  });

  it('patches the profile and the settings on their own endpoints', async () => {
    const tokens = memoryTokenStore({ access: 'a', refresh: 'r' });
    const fetchImpl = vi.fn(async () => jsonResponse(200, { id: 'u1' }));
    const client = new ApiClient({ baseUrl: 'http://api/api/v1', tokens, fetchImpl });

    await client.updateProfile({ display_name: 'Sam' });
    await client.updateSettings({ scheduled_study_days: 0b0111111, expected_version: 3 });

    const profile = requestOfCall(fetchImpl, 0);
    expect(profile.url).toBe('http://api/api/v1/me');
    expect(profile.init.method).toBe('PATCH');

    const settings = requestOfCall(fetchImpl, 1);
    expect(settings.url).toBe('http://api/api/v1/me/settings');
    // The version has to survive onto the wire: without it the server cannot detect a
    // concurrent edit and the write silently becomes last-write-wins.
    expect(JSON.parse(String(settings.init.body))).toEqual({
      scheduled_study_days: 0b0111111,
      expected_version: 3,
    });
  });
});
