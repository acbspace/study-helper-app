/**
 * Friends screen states: loading, populated (friends + incoming requests), search results,
 * and the two most important actions (accept an incoming request, add a searched user).
 *
 * The query hooks are mocked so the test verifies what the user sees and does, not the
 * network plumbing.
 */

import React from 'react';

import { fireEvent, render, screen } from '@testing-library/react-native';

import type { PublicUser } from '@study-league/api-client';

import { ThemeProvider } from '@/theme/ThemeProvider';

import { FriendsScreen } from '../FriendsScreen';

const mockFriends = jest.fn();
const mockRequests = jest.fn();
const mockSearch = jest.fn();
const mockSendMutate = jest.fn();
const mockAcceptMutate = jest.fn();
const mockDeclineMutate = jest.fn();
const mockRemoveMutate = jest.fn();

const mockPresence = jest.fn();

jest.mock('@/features/api/queries', () => ({
  useFriends: () => mockFriends(),
  useFriendRequests: () => mockRequests(),
  useSearchUsers: () => mockSearch(),
  useFriendsPresence: () => mockPresence(),
  useSendFriendRequest: () => ({ mutate: mockSendMutate, isPending: false }),
  useAcceptFriendRequest: () => ({ mutate: mockAcceptMutate, isPending: false }),
  useDeclineFriendRequest: () => ({ mutate: mockDeclineMutate, isPending: false }),
  useRemoveFriendship: () => ({ mutate: mockRemoveMutate, isPending: false }),
}));

function person(overrides: Partial<PublicUser> & { id: string }): PublicUser {
  return {
    username: overrides.id,
    display_name: overrides.id,
    avatar_url: null,
    country_code: null,
    study_category: 'software_engineering',
    ...overrides,
  };
}

function renderScreen() {
  return render(
    <ThemeProvider>
      <FriendsScreen />
    </ThemeProvider>,
  );
}

describe('FriendsScreen', () => {
  beforeEach(() => {
    mockFriends.mockReturnValue({
      isLoading: false,
      isError: false,
      data: [
        { friendship_id: 'f1', since: '2026-07-01T00:00:00Z', user: person({ id: 'bob', display_name: 'Bob' }) },
      ],
      refetch: jest.fn(),
    });
    mockRequests.mockReturnValue({
      isLoading: false,
      isError: false,
      data: {
        incoming: [
          {
            friendship_id: 'req1',
            direction: 'incoming',
            status: 'pending',
            created_at: '2026-07-20T00:00:00Z',
            user: person({ id: 'dave', display_name: 'Dave' }),
          },
        ],
        outgoing: [],
      },
      refetch: jest.fn(),
    });
    mockSearch.mockReturnValue({ isLoading: false, data: [] });
    mockPresence.mockReturnValue({ data: [] });
  });

  afterEach(() => jest.clearAllMocks());

  it('shows a loading state before anything arrives', () => {
    mockFriends.mockReturnValue({ isLoading: true, data: undefined, isError: false });
    mockRequests.mockReturnValue({ isLoading: true, data: undefined, isError: false });

    renderScreen();
    expect(screen.getByText('Loading friends…')).toBeTruthy();
  });

  it('renders friends and incoming requests', () => {
    renderScreen();
    expect(screen.getByTestId('friends-screen')).toBeTruthy();
    expect(screen.getByText('Bob')).toBeTruthy(); // a friend
    expect(screen.getByText('Dave')).toBeTruthy(); // an incoming request
    expect(screen.getByTestId('friends-incoming')).toBeTruthy();
  });

  it('accepts an incoming request', () => {
    renderScreen();
    fireEvent.press(screen.getByText('Accept'));
    expect(mockAcceptMutate).toHaveBeenCalledWith('req1');
  });

  it('sends a request from a search result', () => {
    mockSearch.mockReturnValue({
      isLoading: false,
      data: [
        {
          user: person({ id: 'charlie', display_name: 'Charlie' }),
          relationship: 'none',
          friendship_id: null,
        },
      ],
    });

    renderScreen();
    expect(screen.getByText('Charlie')).toBeTruthy();
    fireEvent.press(screen.getByText('Add'));
    expect(mockSendMutate).toHaveBeenCalledWith({ user_id: 'charlie' });
  });

  it('marks a friend who is studying right now', () => {
    mockPresence.mockReturnValue({
      data: [
        {
          user: person({ id: 'bob', display_name: 'Bob' }),
          state: 'studying',
          subject_id: null,
          started_at: null,
          updated_at: '2026-07-24T00:00:00Z',
        },
      ],
    });

    renderScreen();
    expect(screen.getByText('Studying now')).toBeTruthy();
  });

  it('shows an empty state when there are no friends yet', () => {
    mockFriends.mockReturnValue({ isLoading: false, isError: false, data: [], refetch: jest.fn() });
    mockRequests.mockReturnValue({
      isLoading: false,
      isError: false,
      data: { incoming: [], outgoing: [] },
      refetch: jest.fn(),
    });

    renderScreen();
    expect(screen.getByText('No friends yet')).toBeTruthy();
  });
});
