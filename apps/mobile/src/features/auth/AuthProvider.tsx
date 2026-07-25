/**
 * Authentication context.
 *
 * Owns the single ApiClient instance, restores the session on launch, and clears local
 * data on sign-out so two accounts never share a device cache.
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { ApiClient, ApiError, type Me } from '@study-league/api-client';

import { config } from '@/lib/config';
import { clearAllLocalData } from '@/lib/database';
import { getOrCreateDeviceId, secureTokenStore } from '@/lib/tokenStore';
import { newUuid } from '@/lib/uuid';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

interface AuthContextValue {
  status: AuthStatus;
  user: Me | null;
  client: ApiClient;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (input: {
    email: string;
    password: string;
    username: string;
    timezone?: string;
  }) => Promise<void>;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<Me | null>(null);
  const [deviceId, setDeviceId] = useState<string | undefined>();

  useEffect(() => {
    getOrCreateDeviceId(newUuid)
      .then(setDeviceId)
      .catch(() => {
        // Device id is an integrity signal, not a requirement; proceed without it.
      });
  }, []);

  const client = useMemo(
    () =>
      new ApiClient({
        baseUrl: config.apiBaseUrl,
        tokens: secureTokenStore,
        deviceId,
        onAuthFailure: () => {
          setUser(null);
          setStatus('unauthenticated');
        },
      }),
    [deviceId],
  );

  /** Restore a signed-in session on launch, tolerating being offline. */
  const restore = useCallback(async () => {
    const token = await secureTokenStore.getAccessToken();
    if (!token) {
      setStatus('unauthenticated');
      return;
    }
    try {
      const me = await client.getMe();
      setUser(me);
      setStatus('authenticated');
    } catch (error) {
      // Offline at launch is not a sign-out: keep the stored tokens and let the user in,
      // relying on cached data until the network returns.
      if (error instanceof ApiError && error.code === 'network_error') {
        setStatus('authenticated');
        return;
      }
      await secureTokenStore.clear();
      setStatus('unauthenticated');
    }
  }, [client]);

  useEffect(() => {
    void restore();
  }, [restore]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const response = await client.login(email, password);
      setUser(response.user);
      setStatus('authenticated');
    },
    [client],
  );

  const signUp = useCallback(
    async (input: { email: string; password: string; username: string; timezone?: string }) => {
      const response = await client.register({
        ...input,
        timezone: input.timezone ?? resolveDeviceTimezone(),
      });
      setUser(response.user);
      setStatus('authenticated');
    },
    [client],
  );

  const signOut = useCallback(async () => {
    await client.logout();
    await clearAllLocalData();
    setUser(null);
    setStatus('unauthenticated');
  }, [client]);

  const refreshUser = useCallback(async () => {
    const me = await client.getMe();
    setUser(me);
  }, [client]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, client, signIn, signUp, signOut, refreshUser }),
    [status, user, client, signIn, signUp, signOut, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used inside an AuthProvider.');
  }
  return context;
}

/** The device's IANA zone, so statistics line up with the user's day from the start. */
export function resolveDeviceTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}
