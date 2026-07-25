/** Routes between the sign-in screen and the dashboard based on auth status. */

import type { ReactElement } from 'react';

import { useAuth } from '@/features/auth/AuthProvider';
import { Spinner } from '@/components/ui';
import { Dashboard } from '@/pages/Dashboard';
import { SignIn } from '@/pages/SignIn';
import { theme } from '@/theme';

export function App(): ReactElement {
  const { status } = useAuth();

  if (status === 'loading') {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: theme.background }}>
        <Spinner label="Starting Study League…" />
      </div>
    );
  }

  return status === 'authenticated' ? <Dashboard /> : <SignIn />;
}
