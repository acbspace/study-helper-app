/**
 * The notification inbox — the first client surface to read notifications the server has
 * been producing since M2.
 */

import React from 'react';

import { fireEvent, render, screen } from '@testing-library/react-native';

import type { AppNotification } from '@study-league/api-client';

import { ThemeProvider } from '@/theme/ThemeProvider';

import { NotificationsScreen, formatWhen } from '../NotificationsScreen';

const mockNotifications = jest.fn();
const mockMarkRead = jest.fn();
const mockMarkAllRead = jest.fn();

jest.mock('@/features/api/queries', () => ({
  useNotifications: () => mockNotifications(),
  useMarkNotificationRead: () => ({ mutate: mockMarkRead, isPending: false }),
  useMarkAllNotificationsRead: () => ({ mutate: mockMarkAllRead, isPending: false }),
}));

function notification(overrides: Partial<AppNotification> & { id: string }): AppNotification {
  return {
    kind: 'friend_request',
    title: 'New friend request',
    body: 'Alice wants to study with you.',
    data: {},
    read_at: null,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

function renderScreen() {
  return render(
    <ThemeProvider>
      <NotificationsScreen />
    </ThemeProvider>,
  );
}

describe('NotificationsScreen', () => {
  beforeEach(() => {
    mockNotifications.mockReturnValue({
      isLoading: false,
      isError: false,
      isFetching: false,
      data: [],
      refetch: jest.fn(),
    });
  });
  afterEach(() => jest.clearAllMocks());

  it('shows a loading state first', () => {
    mockNotifications.mockReturnValue({ isLoading: true, isError: false, data: undefined });
    renderScreen();
    expect(screen.getByText('Loading notifications…')).toBeTruthy();
  });

  it('explains an empty inbox', () => {
    renderScreen();
    expect(screen.getByText('Nothing new')).toBeTruthy();
  });

  it('renders a notification', () => {
    mockNotifications.mockReturnValue({
      isLoading: false,
      isError: false,
      isFetching: false,
      data: [notification({ id: 'n1' })],
      refetch: jest.fn(),
    });
    renderScreen();
    expect(screen.getByText('New friend request')).toBeTruthy();
    expect(screen.getByText('Alice wants to study with you.')).toBeTruthy();
  });

  it('marks one notification read', () => {
    mockNotifications.mockReturnValue({
      isLoading: false,
      isError: false,
      isFetching: false,
      data: [notification({ id: 'n1' })],
      refetch: jest.fn(),
    });
    renderScreen();
    fireEvent.press(screen.getByTestId('notification-read-n1'));
    expect(mockMarkRead).toHaveBeenCalledWith('n1');
  });

  it('offers mark-all only while something is unread', () => {
    mockNotifications.mockReturnValue({
      isLoading: false,
      isError: false,
      isFetching: false,
      data: [notification({ id: 'n1' }), notification({ id: 'n2' })],
      refetch: jest.fn(),
    });
    renderScreen();
    fireEvent.press(screen.getByTestId('notifications-mark-all'));
    expect(mockMarkAllRead).toHaveBeenCalled();
  });

  it('hides mark-all once everything is read', () => {
    mockNotifications.mockReturnValue({
      isLoading: false,
      isError: false,
      isFetching: false,
      data: [notification({ id: 'n1', read_at: new Date().toISOString() })],
      refetch: jest.fn(),
    });
    renderScreen();
    expect(screen.queryByTestId('notifications-mark-all')).toBeNull();
    // A read row also loses its per-row action, so there is nothing pointless to tap.
    expect(screen.queryByTestId('notification-read-n1')).toBeNull();
  });

  it('offers a retry when loading failed', () => {
    const refetch = jest.fn();
    mockNotifications.mockReturnValue({
      isLoading: false,
      isError: true,
      isFetching: false,
      data: undefined,
      refetch,
    });
    renderScreen();
    fireEvent.press(screen.getByText('Try again'));
    expect(refetch).toHaveBeenCalled();
  });
});

describe('formatWhen', () => {
  const now = new Date('2026-07-25T12:00:00Z');

  it.each([
    ['2026-07-25T11:59:40Z', 'just now'],
    ['2026-07-25T11:45:00Z', '15m ago'],
    ['2026-07-25T09:00:00Z', '3h ago'],
    ['2026-07-23T12:00:00Z', '2d ago'],
  ])('renders %s as %s', (timestamp, expected) => {
    expect(formatWhen(timestamp, now)).toBe(expected);
  });

  it('falls back to a date once a week has passed', () => {
    // Beyond a week "37d ago" stops being useful; a date is easier to place.
    expect(formatWhen('2026-06-01T12:00:00Z', now)).toContain('2026');
  });

  it('never reports a future timestamp as negative', () => {
    // Clock skew between device and server is normal and must not render "-3m ago".
    expect(formatWhen('2026-07-25T12:05:00Z', now)).toBe('just now');
  });
});
