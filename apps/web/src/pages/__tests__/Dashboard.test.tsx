import { ApiError } from '@study-league/api-client';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Dashboard } from '../Dashboard';

const useStatisticsSummary = vi.fn();
const useLeagueStanding = vi.fn();
const useFriendsPresence = vi.fn();
const signOut = vi.fn();

vi.mock('@/features/auth/AuthProvider', () => ({
  useAuth: () => ({ user: { profile: { display_name: 'Ada' } }, signOut }),
}));

vi.mock('@/features/api/queries', () => ({
  useStatisticsSummary: () => useStatisticsSummary(),
  useLeagueStanding: () => useLeagueStanding(),
  useFriendsPresence: () => useFriendsPresence(),
}));

const summary = {
  isLoading: false,
  isError: false,
  data: {
    today: {
      verified_seconds: 2 * 3600 + 15 * 60,
      manual_seconds: 0,
      current_streak_days: 4,
    },
    week: {
      verified_seconds: 8 * 3600,
      manual_seconds: 0,
      scheduled_days: 5,
      scheduled_days_met: 3,
      days: [
        { day: '2026-07-20', verified_seconds: 3600, goal_met: true },
        { day: '2026-07-21', verified_seconds: 1800, goal_met: false },
        { day: '2026-07-22', verified_seconds: 0, goal_met: false },
        { day: '2026-07-23', verified_seconds: 5400, goal_met: true },
        { day: '2026-07-24', verified_seconds: 0, goal_met: false },
        { day: '2026-07-25', verified_seconds: 0, goal_met: false },
        { day: '2026-07-26', verified_seconds: 0, goal_met: false },
      ],
    },
  },
};

describe('Dashboard', () => {
  afterEach(() => vi.clearAllMocks());

  function setup() {
    useStatisticsSummary.mockReturnValue(summary);
    useFriendsPresence.mockReturnValue({ data: [] });
  }

  it('renders the headline stats and the signed-in user', () => {
    setup();
    useLeagueStanding.mockReturnValue({ isLoading: false, data: undefined, error: undefined });

    render(<Dashboard />);
    expect(screen.getByText('Signed in as Ada')).toBeInTheDocument();
    expect(screen.getByTestId('stat-today')).toHaveTextContent('2h 15m');
    expect(screen.getByText('4 days')).toBeInTheDocument();
    expect(screen.getByText('3/5')).toBeInTheDocument();
  });

  it('shows the league standing when enrolled', () => {
    setup();
    useLeagueStanding.mockReturnValue({
      isLoading: false,
      data: {
        division_name: 'Bronze',
        category_name: 'General',
        total_points: 340,
        rank: 2,
        cohort_size: 5,
      },
      error: undefined,
    });

    render(<Dashboard />);
    expect(screen.getByText('340 points')).toBeInTheDocument();
    expect(screen.getByText('Rank 2 of 5')).toBeInTheDocument();
  });

  it('treats "no season" as a normal state, not an error', () => {
    setup();
    useLeagueStanding.mockReturnValue({
      isLoading: false,
      data: undefined,
      error: new ApiError(404, 'no_active_season', 'none'),
    });

    render(<Dashboard />);
    expect(screen.getByText('No season is running right now.')).toBeInTheDocument();
  });

  it('shows friends who are studying', () => {
    useStatisticsSummary.mockReturnValue(summary);
    useLeagueStanding.mockReturnValue({ isLoading: false, data: undefined, error: undefined });
    useFriendsPresence.mockReturnValue({
      data: [
        {
          user: { id: 'u1', display_name: 'Bob' },
          state: 'studying',
        },
      ],
    });

    render(<Dashboard />);
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.getByText('Studying')).toBeInTheDocument();
  });
});
