/**
 * Settings screen: the surface that makes user_settings reachable at all.
 *
 * The assertions concentrate on the things that were previously impossible — changing the
 * scheduled-study-days bitmask, flipping the privacy switches, and signing out — plus the
 * optimistic-concurrency contract, since a settings write that omits `expected_version`
 * silently reintroduces last-write-wins across devices.
 */

import React from 'react';

import { fireEvent, render, screen } from '@testing-library/react-native';

import { ApiError } from '@study-league/api-client';
import type { Me } from '@study-league/api-client';

import { ThemeProvider } from '@/theme/ThemeProvider';

import { SettingsScreen } from '../SettingsScreen';

const mockSignOut = jest.fn();
const mockExport = jest.fn();
const mockUpdateSettings = jest.fn();
const mockUpdateProfile = jest.fn();
const mockUnblock = jest.fn();
const mockBlocked = jest.fn();
const mockSettingsMutation = jest.fn();
const mockProfileMutation = jest.fn();

let mockCurrentUser: Me | null = null;

jest.mock('@/features/auth/AuthProvider', () => ({
  useAuth: () => ({
    user: mockCurrentUser,
    signOut: mockSignOut,
    client: { exportMyData: mockExport },
  }),
  resolveDeviceTimezone: () => 'Europe/Berlin',
}));

jest.mock('@/features/api/queries', () => ({
  useUpdateSettings: () => mockSettingsMutation(),
  useUpdateProfile: () => mockProfileMutation(),
  useBlockedUsers: () => mockBlocked(),
  useUnblockUser: () => ({ mutate: mockUnblock, isPending: false }),
}));

/** Monday–Friday, matching the registration default. */
const WEEKDAYS_MASK = 0b0011111;

function makeUser(overrides: Partial<Me['settings']> = {}): Me {
  return {
    id: 'u1',
    email: 'demo@example.com',
    profile: {
      username: 'demo',
      display_name: 'Demo Student',
      avatar_url: null,
      country_code: null,
      study_category: 'university',
      bio: null,
    },
    settings: {
      timezone: 'UTC',
      language: 'en',
      daily_goal_minutes: 180,
      weekly_goal_minutes: 900,
      scheduled_study_days: WEEKDAYS_MASK,
      pomodoro_focus_minutes: 25,
      pomodoro_break_minutes: 5,
      privacy_show_subject: true,
      privacy_show_presence: true,
      notifications_enabled: true,
      version: 7,
      ...overrides,
    },
  };
}

function renderScreen() {
  return render(
    <ThemeProvider>
      <SettingsScreen />
    </ThemeProvider>,
  );
}

describe('SettingsScreen', () => {
  beforeEach(() => {
    mockCurrentUser = makeUser();
    mockSettingsMutation.mockReturnValue({
      mutate: mockUpdateSettings,
      isPending: false,
      isError: false,
      error: null,
    });
    mockProfileMutation.mockReturnValue({
      mutate: mockUpdateProfile,
      isPending: false,
      isError: false,
      error: null,
    });
    mockBlocked.mockReturnValue({ isLoading: false, data: [] });
  });
  afterEach(() => jest.clearAllMocks());

  it('waits for the user rather than rendering empty fields', () => {
    mockCurrentUser = null;
    renderScreen();
    expect(screen.getByText('Loading your settings…')).toBeTruthy();
  });

  it('shows how many study days are scheduled', () => {
    renderScreen();
    expect(screen.getByText('5 days scheduled')).toBeTruthy();
  });

  it('adds a study day by flipping its bit', () => {
    renderScreen();
    fireEvent.press(screen.getByTestId('settings-day-sat'));
    expect(mockUpdateSettings).toHaveBeenCalledWith({
      scheduled_study_days: 0b0111111,
      expected_version: 7,
    });
  });

  it('removes a study day by flipping its bit', () => {
    renderScreen();
    fireEvent.press(screen.getByTestId('settings-day-mon'));
    expect(mockUpdateSettings).toHaveBeenCalledWith({
      scheduled_study_days: 0b0011110,
      expected_version: 7,
    });
  });

  it('turns presence off immediately, without a separate save', () => {
    renderScreen();
    fireEvent(screen.getByTestId('settings-show-presence'), 'valueChange', false);
    expect(mockUpdateSettings).toHaveBeenCalledWith({
      privacy_show_presence: false,
      expected_version: 7,
    });
  });

  it('saves goals from the entered values', () => {
    renderScreen();
    fireEvent.changeText(screen.getByTestId('settings-daily-goal'), '240');
    fireEvent.press(screen.getByTestId('settings-save-goals'));
    expect(mockUpdateSettings).toHaveBeenCalledWith({
      daily_goal_minutes: 240,
      weekly_goal_minutes: 900,
      expected_version: 7,
    });
  });

  it('clamps an out-of-range goal instead of sending a rejected write', () => {
    renderScreen();
    fireEvent.changeText(screen.getByTestId('settings-daily-goal'), '99999');
    fireEvent.press(screen.getByTestId('settings-save-goals'));
    expect(mockUpdateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ daily_goal_minutes: 1440 }),
    );
  });

  it('falls back to the stored value when a number field is unparseable', () => {
    renderScreen();
    fireEvent.changeText(screen.getByTestId('settings-daily-goal'), 'abc');
    fireEvent.press(screen.getByTestId('settings-save-goals'));
    expect(mockUpdateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ daily_goal_minutes: 180 }),
    );
  });

  it('fills the time zone from the device', () => {
    renderScreen();
    fireEvent.press(screen.getByTestId('settings-use-device-timezone'));
    fireEvent.press(screen.getByTestId('settings-save-timezone'));
    expect(mockUpdateSettings).toHaveBeenCalledWith({
      timezone: 'Europe/Berlin',
      expected_version: 7,
    });
  });

  it('saves the profile separately from settings', () => {
    renderScreen();
    fireEvent.changeText(screen.getByTestId('settings-display-name'), 'Sam');
    fireEvent.press(screen.getByTestId('settings-save-profile'));
    expect(mockUpdateProfile).toHaveBeenCalledWith({ display_name: 'Sam', bio: '' });
    expect(mockUpdateSettings).not.toHaveBeenCalled();
  });

  it('explains a version conflict in the user’s terms', () => {
    mockSettingsMutation.mockReturnValue({
      mutate: mockUpdateSettings,
      isPending: false,
      isError: true,
      error: new ApiError(409, 'version_conflict', 'Conflict.'),
    });
    renderScreen();
    expect(screen.getByText(/changed on another device/)).toBeTruthy();
  });

  it('lists blocked users and unblocks one', () => {
    mockBlocked.mockReturnValue({
      isLoading: false,
      data: [
        {
          id: 'u9',
          username: 'noisy',
          display_name: 'Noisy Neighbour',
          avatar_url: null,
          country_code: null,
          study_category: 'university',
        },
      ],
    });
    renderScreen();
    fireEvent.press(screen.getByText('Unblock'));
    expect(mockUnblock).toHaveBeenCalledWith('u9');
  });

  it('signs out', () => {
    renderScreen();
    fireEvent.press(screen.getByTestId('settings-sign-out'));
    expect(mockSignOut).toHaveBeenCalled();
  });
});
