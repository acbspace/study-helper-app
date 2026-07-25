/**
 * Today screen states: loading, offline, and populated.
 *
 * Renders the real component tree with mocked query hooks, so the test verifies what the
 * user actually sees in each state rather than internal calls.
 */

import React from 'react';

import { render, screen } from '@testing-library/react-native';

import { ThemeProvider } from '@/theme/ThemeProvider';

import { TodayScreen } from '../TodayScreen';

const mockSummary = jest.fn();
const mockPlan = jest.fn();

jest.mock('@/features/api/queries', () => ({
  useStatisticsSummary: () => mockSummary(),
  useTodayPlan: () => mockPlan(),
  useUpdateTask: () => ({ mutate: jest.fn(), isPending: false }),
}));

jest.mock('@/features/sync/useSync', () => ({
  useSync: () => ({
    pending: 0,
    isSyncing: false,
    lastSyncedAt: null,
    messages: [],
    syncNow: jest.fn(),
    dismissMessages: jest.fn(),
  }),
}));

jest.mock('@/features/timer/timerStore', () => ({
  useTimerStore: (selector: (state: unknown) => unknown) =>
    selector({ state: { status: 'idle' } }),
}));

function renderScreen() {
  return render(
    <ThemeProvider>
      <TodayScreen />
    </ThemeProvider>,
  );
}

const emptyPlan = {
  data: { id: 'p1', plan_date: '2026-07-22', reflection: null, tasks: [] },
  isLoading: false,
};

describe('TodayScreen', () => {
  afterEach(() => jest.clearAllMocks());

  it('shows a loading state before data arrives', () => {
    mockSummary.mockReturnValue({ isLoading: true, data: undefined, isError: false });
    mockPlan.mockReturnValue({ isLoading: true, data: undefined });

    renderScreen();
    expect(screen.getByText('Loading today…')).toBeTruthy();
  });

  it('shows an offline message when the summary fails with a network error', () => {
    const { ApiError } = require('@study-league/api-client');
    mockSummary.mockReturnValue({
      isLoading: false,
      isError: true,
      data: undefined,
      error: new ApiError(0, 'network_error', 'offline'),
      refetch: jest.fn(),
    });
    mockPlan.mockReturnValue(emptyPlan);

    renderScreen();
    expect(screen.getByTestId('today-error')).toBeTruthy();
    expect(screen.getByText("You're offline")).toBeTruthy();
  });

  it('renders verified time, streak, and the start action when data is present', () => {
    mockSummary.mockReturnValue({
      isLoading: false,
      isError: false,
      data: {
        today: {
          date: '2026-07-22',
          timezone: 'Asia/Seoul',
          verified_seconds: 2 * 3600 + 15 * 60,
          manual_seconds: 0,
          excluded_seconds: 0,
          total_seconds: 2 * 3600 + 15 * 60,
          goal_minutes: 180,
          goal_progress: 0.75,
          session_count: 3,
          current_streak_days: 4,
          tasks_total: 2,
          tasks_completed: 1,
          planned_minutes: 90,
          subjects: [
            {
              subject_id: 's1',
              name: 'Algorithms',
              color_hex: '#4F6BED',
              verified_seconds: 2 * 3600 + 15 * 60,
              manual_seconds: 0,
              total_seconds: 2 * 3600 + 15 * 60,
            },
          ],
        },
        week: {
          verified_seconds: 8 * 3600,
          scheduled_days: 5,
          scheduled_days_met: 3,
        },
      },
      refetch: jest.fn(),
    });
    mockPlan.mockReturnValue({
      data: {
        id: 'p1',
        plan_date: '2026-07-22',
        reflection: null,
        tasks: [
          {
            id: 't1',
            title: 'Review recursion',
            status: 'pending',
            subject_id: null,
            estimated_minutes: 30,
            priority: 'normal',
            sort_order: 0,
            completed_at: null,
          },
        ],
      },
      isLoading: false,
    });

    renderScreen();
    expect(screen.getByTestId('today-screen')).toBeTruthy();
    // "2h 15m" appears both as the headline and as the single subject's total.
    expect(screen.getAllByText('2h 15m').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Algorithms')).toBeTruthy(); // subject breakdown
    expect(screen.getByText('Review recursion')).toBeTruthy(); // pending task
    expect(screen.getByTestId('today-start-studying')).toBeTruthy();
    expect(screen.getByText('4')).toBeTruthy(); // streak days
  });
});
