/**
 * Groups screen: loading, populated (my groups + invitations), creating a group, joining a
 * discovered public group, and accepting an invitation. Query hooks are mocked so the test
 * exercises what the user sees and does.
 */

import React from 'react';

import { fireEvent, render, screen } from '@testing-library/react-native';

import type { GroupSummary, PublicUser } from '@study-league/api-client';

import { ThemeProvider } from '@/theme/ThemeProvider';

import { GroupsScreen } from '../GroupsScreen';

const mockGroups = jest.fn();
const mockInvitations = jest.fn();
const mockDiscover = jest.fn();
const mockCreateMutate = jest.fn();
const mockJoinMutate = jest.fn();
const mockJoinByCodeMutate = jest.fn();
const mockLeaveMutate = jest.fn();
const mockAcceptMutate = jest.fn();
const mockDeclineMutate = jest.fn();

jest.mock('@/features/api/queries', () => ({
  useMyGroups: () => mockGroups(),
  useGroupInvitations: () => mockInvitations(),
  useDiscoverGroups: () => mockDiscover(),
  useCreateGroup: () => ({ mutate: mockCreateMutate, isPending: false, isError: false }),
  useJoinGroup: () => ({ mutate: mockJoinMutate, isPending: false }),
  useJoinGroupByCode: () => ({ mutate: mockJoinByCodeMutate, isPending: false, isError: false }),
  useLeaveGroup: () => ({ mutate: mockLeaveMutate, isPending: false }),
  // Each group row carries a report control; the control itself has its own test.
  useReportContent: () => ({
    mutate: jest.fn(),
    reset: jest.fn(),
    isPending: false,
    isError: false,
  }),
  useAcceptGroupInvitation: () => ({ mutate: mockAcceptMutate, isPending: false }),
  useDeclineGroupInvitation: () => ({ mutate: mockDeclineMutate, isPending: false }),
}));

function person(id: string): PublicUser {
  return {
    id,
    username: id,
    display_name: id,
    avatar_url: null,
    country_code: null,
    study_category: 'software_engineering',
  };
}

function group(overrides: Partial<GroupSummary> & { id: string; name: string }): GroupSummary {
  return {
    description: null,
    visibility: 'public',
    member_count: 3,
    max_members: 25,
    owner: person('owner'),
    created_at: '2026-07-01T00:00:00Z',
    my_role: null,
    ...overrides,
  };
}

function renderScreen() {
  return render(
    <ThemeProvider>
      <GroupsScreen />
    </ThemeProvider>,
  );
}

describe('GroupsScreen', () => {
  beforeEach(() => {
    mockGroups.mockReturnValue({
      isLoading: false,
      isError: false,
      data: [group({ id: 'g1', name: 'Algorithms Guild', my_role: 'owner' })],
      refetch: jest.fn(),
    });
    mockInvitations.mockReturnValue({
      isLoading: false,
      isError: false,
      data: [
        {
          id: 'inv1',
          group: group({ id: 'g2', name: 'Chemistry Crew' }),
          inviter: person('dave'),
          expires_at: '2026-08-01T00:00:00Z',
          created_at: '2026-07-20T00:00:00Z',
        },
      ],
      refetch: jest.fn(),
    });
    mockDiscover.mockReturnValue({ isLoading: false, data: [] });
  });

  afterEach(() => jest.clearAllMocks());

  it('shows a loading state before anything arrives', () => {
    mockGroups.mockReturnValue({ isLoading: true, data: undefined, isError: false });
    mockInvitations.mockReturnValue({ isLoading: true, data: undefined, isError: false });

    renderScreen();
    expect(screen.getByText('Loading groups…')).toBeTruthy();
  });

  it('renders my groups and pending invitations', () => {
    renderScreen();
    expect(screen.getByTestId('groups-screen')).toBeTruthy();
    expect(screen.getByText('Algorithms Guild')).toBeTruthy();
    expect(screen.getByText('Chemistry Crew')).toBeTruthy();
    expect(screen.getByTestId('groups-invitations')).toBeTruthy();
  });

  it('creates a group from the form', () => {
    renderScreen();
    fireEvent.changeText(screen.getByTestId('group-name-input'), 'New Squad');
    fireEvent.press(screen.getByText('Create group'));
    expect(mockCreateMutate).toHaveBeenCalledWith(
      { name: 'New Squad', visibility: 'public' },
      expect.anything(),
    );
  });

  it('accepts an invitation', () => {
    renderScreen();
    fireEvent.press(screen.getByText('Accept'));
    expect(mockAcceptMutate).toHaveBeenCalledWith('inv1');
  });

  it('joins a discovered public group', () => {
    mockDiscover.mockReturnValue({
      isLoading: false,
      data: [group({ id: 'g9', name: 'Open Study Hall', my_role: null })],
    });

    renderScreen();
    expect(screen.getByText('Open Study Hall')).toBeTruthy();
    fireEvent.press(screen.getByText('Join'));
    expect(mockJoinMutate).toHaveBeenCalledWith('g9');
  });

  it('shows an empty state when not in any group', () => {
    mockGroups.mockReturnValue({ isLoading: false, isError: false, data: [], refetch: jest.fn() });
    mockInvitations.mockReturnValue({
      isLoading: false,
      isError: false,
      data: [],
      refetch: jest.fn(),
    });

    renderScreen();
    expect(screen.getByText('No groups yet')).toBeTruthy();
  });
});
