/**
 * The League screen's three legitimate states — no season, not enrolled, ranked — plus the
 * score breakdown. Each is a normal state rather than an error, so each gets a test.
 */

import React from 'react';

import { fireEvent, render, screen } from '@testing-library/react-native';

import { ApiError } from '@study-league/api-client';

import { ThemeProvider } from '@/theme/ThemeProvider';

import { LeagueScreen } from '../LeagueScreen';

const mockStanding = jest.fn();
const mockLeaderboard = jest.fn();
const mockBreakdown = jest.fn();
const mockMissions = jest.fn();
const mockEnrollMutate = jest.fn();

jest.mock('@/features/api/queries', () => ({
  useLeagueStanding: () => mockStanding(),
  useLeagueLeaderboard: () => mockLeaderboard(),
  useLeagueBreakdown: () => mockBreakdown(),
  useLeagueMissions: () => mockMissions(),
  useEnrollInLeague: () => ({
    mutate: mockEnrollMutate,
    isPending: false,
    isError: false,
  }),
}));

function renderScreen() {
  return render(
    <ThemeProvider>
      <LeagueScreen />
    </ThemeProvider>,
  );
}

const standingData = {
  season_id: 's1',
  season_name: 'Season 1',
  starts_on: '2026-07-20',
  ends_on: '2026-08-16',
  status: 'active',
  division_tier: 0,
  division_name: 'Bronze',
  cohort_id: 'c1',
  cohort_label: 'Bronze · General · Group A',
  category_name: 'General productivity',
  placement: 'provisional' as const,
  rank: 2,
  cohort_size: 5,
  total_points: 340,
  weeks: [{ week_index: 0, points: 340 }],
};

describe('LeagueScreen', () => {
  beforeEach(() => {
    mockStanding.mockReturnValue({ isLoading: false, isSuccess: false, data: undefined });
    mockLeaderboard.mockReturnValue({ isLoading: false, data: [] });
    mockBreakdown.mockReturnValue({ isLoading: false, data: undefined });
    mockMissions.mockReturnValue({ isLoading: false, data: [] });
  });

  afterEach(() => jest.clearAllMocks());

  it('shows a loading state first', () => {
    mockStanding.mockReturnValue({ isLoading: true, isSuccess: false, data: undefined });
    renderScreen();
    expect(screen.getByText('Loading your league…')).toBeTruthy();
  });

  it('explains when no season is running', () => {
    mockStanding.mockReturnValue({
      isLoading: false,
      isSuccess: false,
      data: undefined,
      error: new ApiError(404, 'no_active_season', 'No league season is running.'),
    });

    renderScreen();
    expect(screen.getByTestId('league-no-season')).toBeTruthy();
    // The rules stay visible even with no season to join.
    expect(screen.getByTestId('league-scoring')).toBeTruthy();
  });

  it('offers to join when not enrolled', () => {
    mockStanding.mockReturnValue({
      isLoading: false,
      isSuccess: false,
      data: undefined,
      error: new ApiError(404, 'not_enrolled', 'You are not in this season yet.'),
    });

    renderScreen();
    expect(screen.getByTestId('league-join')).toBeTruthy();
    fireEvent.press(screen.getByText('Join the league'));
    expect(mockEnrollMutate).toHaveBeenCalled();
  });

  it('shows the standing, cohort ladder and breakdown when ranked', () => {
    mockStanding.mockReturnValue({ isLoading: false, isSuccess: true, data: standingData });
    mockLeaderboard.mockReturnValue({
      isLoading: false,
      data: [
        {
          rank: 1,
          user: {
            id: 'u1',
            username: 'ada',
            display_name: 'Ada',
            avatar_url: null,
            country_code: null,
            study_category: 'software_engineering',
          },
          total_points: 500,
          placement: 'ranked',
          is_me: false,
        },
        {
          rank: 2,
          user: {
            id: 'me',
            username: 'me',
            display_name: 'Me',
            avatar_url: null,
            country_code: null,
            study_category: 'software_engineering',
          },
          total_points: 340,
          placement: 'provisional',
          is_me: true,
        },
      ],
    });
    mockBreakdown.mockReturnValue({
      isLoading: false,
      data: {
        week_index: 0,
        week_start: '2026-07-20',
        total_points: 340,
        scoring_version: 'v1',
        components: [
          { name: 'goal_completion', points: 200, max_points: 400, detail: {} },
          { name: 'focus_sessions', points: 140, max_points: 150, detail: {} },
        ],
        excluded_seconds: 0,
        exclusion_reasons: [],
      },
    });

    renderScreen();
    expect(screen.getByText('340 points')).toBeTruthy();
    expect(screen.getByText('Rank 2 of 5 · Bronze · General · Group A')).toBeTruthy();
    expect(screen.getByText('Ada')).toBeTruthy();
    expect(screen.getByText('Me (you)')).toBeTruthy();
    // "Goal completion" labels both the breakdown row and the always-visible rules card.
    expect(screen.getAllByText('Goal completion').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('200/400')).toBeTruthy();
  });

  it('shows mission progress', () => {
    mockStanding.mockReturnValue({ isLoading: false, isSuccess: true, data: standingData });
    mockMissions.mockReturnValue({
      isLoading: false,
      data: [
        {
          id: 'm1',
          slug: 'finish-what-you-start',
          title: 'Finish what you start',
          description: 'Complete 5 focus sessions.',
          target: 5,
          reward_points: 20,
          progress: 3,
          completed: false,
        },
      ],
    });

    renderScreen();
    expect(screen.getByTestId('league-missions')).toBeTruthy();
    expect(screen.getByText('Finish what you start')).toBeTruthy();
    expect(screen.getByText('3/5')).toBeTruthy();
  });

  it('says so when the week has not been scored yet', () => {
    mockStanding.mockReturnValue({ isLoading: false, isSuccess: true, data: standingData });
    mockBreakdown.mockReturnValue({
      isLoading: false,
      data: undefined,
      error: new ApiError(404, 'score_not_found', 'That week has not been scored yet.'),
    });

    renderScreen();
    expect(
      screen.getByText('This week has not been scored yet. Points appear as the week is scored.'),
    ).toBeTruthy();
  });
});
