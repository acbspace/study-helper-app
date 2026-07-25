/**
 * Goals screen: loading, the countdown/pacing display, creating a goal, and completing one.
 */

import React from 'react';

import { fireEvent, render, screen } from '@testing-library/react-native';

import type { Goal } from '@study-league/api-client';

import { ThemeProvider } from '@/theme/ThemeProvider';

import { GoalsScreen } from '../GoalsScreen';

const mockGoals = jest.fn();
const mockCreateMutate = jest.fn();
const mockUpdateMutate = jest.fn();
const mockDeleteMutate = jest.fn();

jest.mock('@/features/api/queries', () => ({
  useGoals: () => mockGoals(),
  useCreateGoal: () => ({ mutate: mockCreateMutate, isPending: false }),
  useUpdateGoal: () => ({ mutate: mockUpdateMutate, isPending: false }),
  useDeleteGoal: () => ({ mutate: mockDeleteMutate, isPending: false }),
}));

function goal(overrides: Partial<Goal> & { id: string; title: string }): Goal {
  return {
    target_date: null,
    target_weekly_minutes: 0,
    subject_ids: [],
    milestones: [],
    description: null,
    status: 'active',
    completed_at: null,
    days_remaining: null,
    is_overdue: false,
    week_verified_minutes: 0,
    weekly_progress: 0,
    milestones_total: 0,
    milestones_done: 0,
    ...overrides,
  };
}

function renderScreen() {
  return render(
    <ThemeProvider>
      <GoalsScreen />
    </ThemeProvider>,
  );
}

describe('GoalsScreen', () => {
  beforeEach(() => {
    mockGoals.mockReturnValue({ isLoading: false, isError: false, data: [], refetch: jest.fn() });
  });
  afterEach(() => jest.clearAllMocks());

  it('shows a loading state first', () => {
    mockGoals.mockReturnValue({ isLoading: true, data: undefined, isError: false });
    renderScreen();
    expect(screen.getByText('Loading goals…')).toBeTruthy();
  });

  it('shows an empty state with no goals', () => {
    renderScreen();
    expect(screen.getByText('No goals yet')).toBeTruthy();
  });

  it('renders the countdown and weekly pacing', () => {
    mockGoals.mockReturnValue({
      isLoading: false,
      isError: false,
      data: [
        goal({
          id: 'g1',
          title: 'Pass the bar',
          days_remaining: 12,
          target_weekly_minutes: 600,
          week_verified_minutes: 300,
          weekly_progress: 0.5,
        }),
      ],
      refetch: jest.fn(),
    });

    renderScreen();
    expect(screen.getByText('Pass the bar')).toBeTruthy();
    expect(screen.getByText('12 days left')).toBeTruthy();
    expect(screen.getByText('300 / 600 min')).toBeTruthy();
  });

  it('flags an overdue goal', () => {
    mockGoals.mockReturnValue({
      isLoading: false,
      isError: false,
      data: [goal({ id: 'g1', title: 'Late', days_remaining: -2, is_overdue: true })],
      refetch: jest.fn(),
    });

    renderScreen();
    expect(screen.getByText('2 days overdue')).toBeTruthy();
  });

  it('creates a goal', () => {
    renderScreen();
    fireEvent.changeText(screen.getByTestId('goal-title-input'), 'Learn Rust');
    fireEvent.press(screen.getByText('Add goal'));
    expect(mockCreateMutate).toHaveBeenCalledWith(
      { title: 'Learn Rust', target_weekly_minutes: 0 },
      expect.anything(),
    );
  });

  it('marks a goal done', () => {
    mockGoals.mockReturnValue({
      isLoading: false,
      isError: false,
      data: [goal({ id: 'g9', title: 'Finish' })],
      refetch: jest.fn(),
    });

    renderScreen();
    fireEvent.press(screen.getByText('Mark done'));
    expect(mockUpdateMutate).toHaveBeenCalledWith({
      goalId: 'g9',
      changes: { status: 'completed' },
    });
  });
});
