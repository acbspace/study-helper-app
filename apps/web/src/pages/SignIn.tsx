/**
 * Sign-in. The dashboard is read-heavy, so this is the only form a user meets on the way in.
 */

import { useState, type FormEvent, type ReactElement } from 'react';

import { ApiError } from '@study-league/api-client';

import { Button, Card } from '@/components/ui';
import { useAuth } from '@/features/auth/AuthProvider';
import { radius, spacing, theme } from '@/theme';

export function SignIn(): ReactElement {
  const { signIn } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signIn(email.trim(), password);
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === 'invalid_credentials'
          ? 'Email or password is incorrect.'
          : 'Could not sign in. Please try again.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  const inputStyle = {
    padding: spacing.sm,
    borderRadius: radius.md,
    border: `1px solid ${theme.border}`,
    background: theme.surfaceMuted,
    color: theme.textPrimary,
    fontSize: 15,
  } as const;

  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        background: theme.background,
        padding: spacing.lg,
      }}
    >
      <Card testId="sign-in" style={{ width: 360, maxWidth: '100%', gap: spacing.md }}>
        <h1 style={{ color: theme.textPrimary, margin: 0, fontSize: 24 }}>Study League</h1>
        <p style={{ color: theme.textSecondary, margin: 0 }}>Sign in to your dashboard.</p>
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: spacing.sm }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: spacing.xs, color: theme.textSecondary }}>
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
              style={inputStyle}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: spacing.xs, color: theme.textSecondary }}>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              style={inputStyle}
            />
          </label>
          {error ? (
            <p role="alert" style={{ color: theme.danger, margin: 0, fontSize: 14 }}>
              {error}
            </p>
          ) : null}
          <Button type="submit" label={submitting ? 'Signing in…' : 'Sign in'} disabled={submitting} />
        </form>
      </Card>
    </main>
  );
}
