/**
 * ApiClient transport behaviour: auth attachment, refresh-on-401, error mapping, and
 * idempotency headers. Uses a fake fetch so no server is required.
 */

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
    async setTokens(tokens: { access_token: string; refresh_token: string }) {
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
function headersOfCall(fetchImpl: jest.Mock, index: number): Record<string, string> {
  const call = fetchImpl.mock.calls[index];
  if (!call) throw new Error(`Expected a fetch call at index ${index}`);
  return ((call[1] as RequestInit).headers ?? {}) as Record<string, string>;
}

describe('ApiClient', () => {
  it('attaches the bearer token to authenticated requests', async () => {
    const tokens = memoryTokenStore({ access: 'access-1', refresh: 'refresh-1' });
    const fetchImpl = jest.fn(async () => jsonResponse(200, { id: 'u1' }));
    const client = new ApiClient({ baseUrl: 'http://api/api/v1', tokens, fetchImpl });

    await client.getMe();

    expect(headersOfCall(fetchImpl, 0)).toMatchObject({ Authorization: 'Bearer access-1' });
  });

  it('refreshes once on 401 and retries the original request', async () => {
    const tokens = memoryTokenStore({ access: 'expired', refresh: 'refresh-1' });
    const fetchImpl = jest
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
    const onAuthFailure = jest.fn();
    const fetchImpl = jest
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
    const fetchImpl = jest.fn(async () =>
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
    const fetchImpl = jest.fn(async () => {
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
    const fetchImpl = jest.fn(async () => jsonResponse(200, { results: [] }));
    const client = new ApiClient({ baseUrl: 'http://api/api/v1', tokens, fetchImpl });

    await client.syncSessions([], 'key-123');

    expect(headersOfCall(fetchImpl, 0)).toMatchObject({ 'Idempotency-Key': 'key-123' });
  });
});
