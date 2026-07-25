/**
 * Authentication context for the web dashboard.
 *
 * Owns the single ApiClient, restores a session on load, and exposes sign-in / sign-out.
 * Mirrors the mobile AuthProvider, with one deliberate difference: the browser uses the
 * cookie refresh transport, so the long-lived credential is never reachable from JavaScript
 * and the access token is held in memory only (see `lib/tokenStore`).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react';

import { ApiClient, ApiError, type Me } from '@study-league/api-client';

import { config } from '@/lib/config';
import { webTokenStore } from '@/lib/tokenStore';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

interface AuthContextValue {
  status: AuthStatus;
  user: Me | null;
  client: ApiClient;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }): ReactElement {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<Me | null>(null);

  const client = useMemo(
    () =>
      new ApiClient({
        baseUrl: config.apiBaseUrl,
        tokens: webTokenStore,
        // The refresh token lives in an httpOnly cookie the page cannot read.
        refreshTransport: 'cookie',
        onAuthFailure: () => {
          setUser(null);
          setStatus('unauthenticated');
        },
      }),
    [],
  );

  const restore = useCallback(async () => {
    // No local token to inspect: after a reload the access token is gone by design, and the
    // only way to learn whether the session survived is to ask. The request 401s, the client
    // refreshes against the cookie, and the retry succeeds — or it does not and we are
    // genuinely signed out.
    try {
      setUser(await client.getMe());
      setStatus('authenticated');
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      await webTokenStore.clear();
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

  const signOut = useCallback(async () => {
    await client.logout();
    setUser(null);
    setStatus('unauthenticated');
  }, [client]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, client, signIn, signOut }),
    [status, user, client, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside an AuthProvider.');
  return context;
}
