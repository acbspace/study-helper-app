/**
 * Friends — find people, manage requests, and see your study friends.
 *
 * Each row's action reflects the relationship the server reports, so the same person shows
 * "Add", "Requested", "Accept", or "Friends" depending on where you already are. Blocking is
 * deliberately quiet: a user who blocked you simply never appears here.
 */

import React, { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, TextInput, View } from 'react-native';

import type { PresenceState, PublicUser, UserSearchResult } from '@study-league/api-client';
import { minTouchTarget, radius, spacing } from '@study-league/design-tokens';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { EmptyState, ErrorState, LoadingState } from '@/components/StateViews';
import { Text } from '@/components/Text';
import {
  useAcceptFriendRequest,
  useDeclineFriendRequest,
  useFriendRequests,
  useFriends,
  useFriendsPresence,
  useRemoveFriendship,
  useSendFriendRequest,
  useSearchUsers,
} from '@/features/api/queries';
import { useTheme } from '@/theme/ThemeProvider';

export function FriendsScreen(): React.ReactElement {
  const friends = useFriends();
  const requests = useFriendRequests();
  const presence = useFriendsPresence();
  const presenceByUser = new Map<string, PresenceState>(
    (presence.data ?? []).map((row) => [row.user.id, row.state]),
  );

  const firstLoad = friends.isLoading && !friends.data && requests.isLoading && !requests.data;
  if (firstLoad) return <LoadingState label="Loading friends…" />;

  if (friends.isError && !friends.data && requests.isError && !requests.data) {
    return (
      <ErrorState
        testID="friends-error"
        description="We could not load your friends."
        onRetry={() => {
          void friends.refetch();
          void requests.refetch();
        }}
      />
    );
  }

  const incoming = requests.data?.incoming ?? [];
  const outgoing = requests.data?.outgoing ?? [];
  const friendList = friends.data ?? [];

  return (
    <ScrollView testID="friends-screen" contentContainerStyle={styles.content}>
      <FindPeopleCard />

      {incoming.length > 0 ? (
        <Card testID="friends-incoming">
          <Text variant="heading">Requests</Text>
          {incoming.map((request) => (
            <PersonRow
              key={request.friendship_id}
              user={request.user}
              action={<IncomingActions friendshipId={request.friendship_id} />}
            />
          ))}
        </Card>
      ) : null}

      {outgoing.length > 0 ? (
        <Card testID="friends-outgoing">
          <Text variant="heading">Sent requests</Text>
          {outgoing.map((request) => (
            <PersonRow
              key={request.friendship_id}
              user={request.user}
              action={<CancelAction friendshipId={request.friendship_id} />}
            />
          ))}
        </Card>
      ) : null}

      <Card testID="friends-list">
        <Text variant="heading">Your friends</Text>
        {friendList.length === 0 ? (
          <EmptyState
            title="No friends yet"
            description="Search above to find study partners and send a request."
          />
        ) : (
          friendList.map((friend) => (
            <PersonRow
              key={friend.friendship_id}
              user={friend.user}
              presenceState={presenceByUser.get(friend.user.id)}
              action={<RemoveAction friendshipId={friend.friendship_id} />}
            />
          ))
        )}
      </Card>
    </ScrollView>
  );
}

function FindPeopleCard(): React.ReactElement {
  const { theme, fontSize } = useTheme();
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');

  // Debounce so a search does not fire on every keystroke.
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(query), 250);
    return () => clearTimeout(handle);
  }, [query]);

  const results = useSearchUsers(debounced);
  const active = debounced.trim().length >= 2;

  return (
    <Card>
      <Text variant="heading">Find people</Text>
      <TextInput
        testID="friends-search-input"
        value={query}
        onChangeText={setQuery}
        placeholder="Search by name or username"
        placeholderTextColor={theme.textSecondary}
        accessibilityLabel="Search for people"
        autoCapitalize="none"
        autoCorrect={false}
        maxLength={60}
        style={{
          minHeight: minTouchTarget,
          borderRadius: radius.md,
          borderWidth: 1,
          borderColor: theme.border,
          backgroundColor: theme.surfaceMuted,
          color: theme.textPrimary,
          paddingHorizontal: spacing.md,
          fontSize: fontSize('body'),
        }}
      />

      {active && results.isLoading ? (
        <Text variant="caption" color="secondary">
          Searching…
        </Text>
      ) : null}

      {active && !results.isLoading && (results.data?.length ?? 0) === 0 ? (
        <Text variant="caption" color="secondary" testID="friends-search-empty">
          No one found for “{debounced.trim()}”.
        </Text>
      ) : null}

      {results.data?.map((result) => (
        <PersonRow
          key={result.user.id}
          user={result.user}
          action={<SearchAction result={result} />}
        />
      ))}
    </Card>
  );
}

function PersonRow({
  user,
  action,
  presenceState,
}: {
  user: PublicUser;
  action: React.ReactNode;
  presenceState?: PresenceState;
}): React.ReactElement {
  const { theme } = useTheme();
  const initial = (user.display_name || user.username).charAt(0).toUpperCase();
  const presence = presenceState ? PRESENCE_LABELS[presenceState] : null;
  return (
    <View style={styles.row}>
      <View style={[styles.avatar, { backgroundColor: theme.accentMuted }]}>
        <Text variant="label" color="accent">
          {initial}
        </Text>
      </View>
      <View style={styles.flex}>
        <Text variant="body">{user.display_name}</Text>
        {presence ? (
          <View style={styles.presenceRow}>
            <View style={[styles.dot, { backgroundColor: theme[presence.tone] }]} />
            <Text variant="caption" color="secondary">
              {presence.label}
            </Text>
          </View>
        ) : (
          <Text variant="caption" color="secondary">
            @{user.username}
          </Text>
        )}
      </View>
      {action}
    </View>
  );
}

const PRESENCE_LABELS: Record<PresenceState, { label: string; tone: 'verified' | 'streak' }> = {
  studying: { label: 'Studying now', tone: 'verified' },
  break: { label: 'On a break', tone: 'streak' },
  idle: { label: 'Online', tone: 'streak' },
};

function SearchAction({ result }: { result: UserSearchResult }): React.ReactElement {
  const send = useSendFriendRequest();
  const accept = useAcceptFriendRequest();

  switch (result.relationship) {
    case 'friends':
      return (
        <Text variant="label" color="secondary">
          Friends
        </Text>
      );
    case 'request_sent':
      return (
        <Text variant="label" color="secondary">
          Requested
        </Text>
      );
    case 'request_received':
      return (
        <Button
          label="Accept"
          onPress={() => result.friendship_id && accept.mutate(result.friendship_id)}
          loading={accept.isPending}
          accessibilityHint={`Accept ${result.user.display_name}'s friend request`}
        />
      );
    case 'blocked':
      return (
        <Text variant="label" color="secondary">
          Blocked
        </Text>
      );
    default:
      return (
        <Button
          label="Add"
          variant="secondary"
          onPress={() => send.mutate({ user_id: result.user.id })}
          loading={send.isPending}
          accessibilityHint={`Send ${result.user.display_name} a friend request`}
        />
      );
  }
}

function IncomingActions({ friendshipId }: { friendshipId: string }): React.ReactElement {
  const accept = useAcceptFriendRequest();
  const decline = useDeclineFriendRequest();
  const busy = accept.isPending || decline.isPending;
  return (
    <View style={styles.actions}>
      <Button
        label="Decline"
        variant="ghost"
        onPress={() => decline.mutate(friendshipId)}
        disabled={busy}
      />
      <Button label="Accept" onPress={() => accept.mutate(friendshipId)} loading={accept.isPending} />
    </View>
  );
}

function CancelAction({ friendshipId }: { friendshipId: string }): React.ReactElement {
  const remove = useRemoveFriendship();
  return (
    <Button
      label="Cancel"
      variant="ghost"
      onPress={() => remove.mutate(friendshipId)}
      loading={remove.isPending}
    />
  );
}

function RemoveAction({ friendshipId }: { friendshipId: string }): React.ReactElement {
  const remove = useRemoveFriendship();
  return (
    <Button
      label="Remove"
      variant="ghost"
      onPress={() => remove.mutate(friendshipId)}
      loading={remove.isPending}
      accessibilityHint="Removes this friend"
    />
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xxxl },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actions: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  presenceRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  dot: { width: 8, height: 8, borderRadius: 4 },
  flex: { flex: 1 },
});
