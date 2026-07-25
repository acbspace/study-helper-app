import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from '../App';

const useAuth = vi.fn();

vi.mock('@/features/auth/AuthProvider', () => ({
  useAuth: () => useAuth(),
}));

// The dashboard's own data hooks are mocked so the authenticated branch renders in isolation.
vi.mock('@/features/api/queries', () => ({
  useStatisticsSummary: () => ({ isLoading: true, data: undefined }),
  useLeagueStanding: () => ({ isLoading: true, data: undefined }),
  useFriendsPresence: () => ({ data: [] }),
}));

describe('App', () => {
  afterEach(() => vi.clearAllMocks());

  it('shows a splash while auth is loading', () => {
    useAuth.mockReturnValue({ status: 'loading' });
    render(<App />);
    expect(screen.getByText('Starting Study League…')).toBeInTheDocument();
  });

  it('shows the sign-in screen when unauthenticated', () => {
    useAuth.mockReturnValue({ status: 'unauthenticated' });
    render(<App />);
    expect(screen.getByTestId('sign-in')).toBeInTheDocument();
  });

  it('shows the dashboard when authenticated', () => {
    useAuth.mockReturnValue({
      status: 'authenticated',
      user: { profile: { display_name: 'Ada' } },
      signOut: vi.fn(),
    });
    render(<App />);
    expect(screen.getByText('Signed in as Ada')).toBeInTheDocument();
  });
});
