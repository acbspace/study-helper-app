/**
 * Authentication context for the web dashboard.
 *
 * Owns the single ApiClient, restores a session from stored tokens on load, and exposes
 * sign-in / sign-out. Mirrors the mobile AuthProvider so behaviour is consistent across
 * clients — the only difference is the token store (localStorage here).
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
        onAuthFailure: () => {
          setUser(null);
          setStatus('unauthenticated');
        },
      }),
    [],
  );

  const restore = useCallback(async () => {
    const token = await webTokenStore.getAccessToken();
    if (!token) {
      setStatus('unauthenticated');
      return;
    }
    try {
      setUser(await client.getMe());
      setStatus('authenticated');
    } catch (error) {
      // Offline at load is not a sign-out — keep the session and let cached data fill in.
      if (error instanceof ApiError && error.code === 'network_error') {
        setStatus('authenticated');
        return;
      }
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
