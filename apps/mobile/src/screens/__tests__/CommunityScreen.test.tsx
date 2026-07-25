/**
 * Community screen: the feed, creating a post, and reacting to one.
 */

import React from 'react';

import { fireEvent, render, screen } from '@testing-library/react-native';

import type { CommunityPost } from '@study-league/api-client';

import { ThemeProvider } from '@/theme/ThemeProvider';

import { CommunityScreen } from '../CommunityScreen';

const mockPosts = jest.fn();
const mockCreateMutate = jest.fn();
const mockReactMutate = jest.fn();
const mockBookmarkMutate = jest.fn();

jest.mock('@/features/api/queries', () => ({
  usePosts: () => mockPosts(),
  useCreatePost: () => ({ mutate: mockCreateMutate, isPending: false }),
  useReactToPost: () => ({ mutate: mockReactMutate, isPending: false }),
  useToggleBookmark: () => ({ mutate: mockBookmarkMutate, isPending: false }),
}));

function post(overrides: Partial<CommunityPost> & { id: string; title: string }): CommunityPost {
  return {
    author: {
      id: 'u1',
      username: 'ada',
      display_name: 'Ada',
      avatar_url: null,
      country_code: null,
      study_category: 'software_engineering',
    },
    topic: 'general',
    body: 'Body text',
    created_at: '2026-07-24T00:00:00Z',
    comment_count: 0,
    reaction_count: 0,
    my_reaction: null,
    bookmarked: false,
    ...overrides,
  };
}

function renderScreen() {
  return render(
    <ThemeProvider>
      <CommunityScreen />
    </ThemeProvider>,
  );
}

describe('CommunityScreen', () => {
  beforeEach(() => {
    mockPosts.mockReturnValue({ isLoading: false, isError: false, data: [], refetch: jest.fn() });
  });
  afterEach(() => jest.clearAllMocks());

  it('shows a loading state first', () => {
    mockPosts.mockReturnValue({ isLoading: true, data: undefined, isError: false });
    renderScreen();
    expect(screen.getByText('Loading community…')).toBeTruthy();
  });

  it('shows an empty state with no posts', () => {
    renderScreen();
    expect(screen.getByText('No posts yet')).toBeTruthy();
  });

  it('renders posts', () => {
    mockPosts.mockReturnValue({
      isLoading: false,
      isError: false,
      data: [post({ id: 'p1', title: 'Staying consistent', reaction_count: 3 })],
      refetch: jest.fn(),
    });

    renderScreen();
    expect(screen.getByText('Staying consistent')).toBeTruthy();
    expect(screen.getByText('3 · 0 comments')).toBeTruthy();
  });

  it('creates a post when title and body are present', () => {
    renderScreen();
    fireEvent.changeText(screen.getByTestId('post-title-input'), 'Hello world');
    fireEvent.changeText(screen.getByTestId('post-body-input'), 'My first post');
    fireEvent.press(screen.getByText('Post'));
    expect(mockCreateMutate).toHaveBeenCalledWith(
      { title: 'Hello world', body: 'My first post' },
      expect.anything(),
    );
  });

  it('reacts to a post', () => {
    mockPosts.mockReturnValue({
      isLoading: false,
      isError: false,
      data: [post({ id: 'p9', title: 'React to me' })],
      refetch: jest.fn(),
    });

    renderScreen();
    fireEvent.press(screen.getByText('♡ Like'));
    expect(mockReactMutate).toHaveBeenCalledWith({ postId: 'p9', emoji: 'like' });
  });
});
