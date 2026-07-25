/**
 * Groups — create or join study groups, manage invitations, and discover public ones.
 *
 * Kept to a single scrollable surface: create, join-by-code, pending invitations, the groups
 * you are in, and a public search. Per-group admin (roles, kicking, invites) lives behind the
 * API and a future detail screen; this screen covers the everyday member journey.
 */

import React, { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, TextInput, View } from 'react-native';

import type { GroupSummary } from '@study-league/api-client';
import { minTouchTarget, radius, spacing } from '@study-league/design-tokens';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { EmptyState, ErrorState, LoadingState } from '@/components/StateViews';
import { Text } from '@/components/Text';
import {
  useAcceptGroupInvitation,
  useCreateGroup,
  useDeclineGroupInvitation,
  useDiscoverGroups,
  useGroupInvitations,
  useJoinGroup,
  useJoinGroupByCode,
  useLeaveGroup,
  useMyGroups,
} from '@/features/api/queries';
import { useTheme } from '@/theme/ThemeProvider';

type Visibility = 'public' | 'private' | 'invite';

const VISIBILITY_LABELS: Record<Visibility, string> = {
  public: 'Public',
  invite: 'Invite code',
  private: 'Private',
};

export function GroupsScreen(): React.ReactElement {
  const groups = useMyGroups();
  const invitations = useGroupInvitations();

  if (groups.isLoading && !groups.data && invitations.isLoading && !invitations.data) {
    return <LoadingState label="Loading groups…" />;
  }

  if (groups.isError && !groups.data && invitations.isError && !invitations.data) {
    return (
      <ErrorState
        testID="groups-error"
        description="We could not load your groups."
        onRetry={() => {
          void groups.refetch();
          void invitations.refetch();
        }}
      />
    );
  }

  const invites = invitations.data ?? [];
  const mine = groups.data ?? [];

  return (
    <ScrollView testID="groups-screen" contentContainerStyle={styles.content}>
      <CreateGroupCard />
      <JoinByCodeCard />

      {invites.length > 0 ? (
        <Card testID="groups-invitations">
          <Text variant="heading">Invitations</Text>
          {invites.map((invite) => (
            <GroupRow
              key={invite.id}
              group={invite.group}
              subtitle={`Invited by @${invite.inviter.username}`}
              action={<InvitationActions invitationId={invite.id} />}
            />
          ))}
        </Card>
      ) : null}

      <Card testID="groups-list">
        <Text variant="heading">Your groups</Text>
        {mine.length === 0 ? (
          <EmptyState
            title="No groups yet"
            description="Create one above, join with a code, or discover public groups below."
          />
        ) : (
          mine.map((group) => (
            <GroupRow key={group.id} group={group} action={<LeaveAction groupId={group.id} />} />
          ))
        )}
      </Card>

      <DiscoverCard />
    </ScrollView>
  );
}

function CreateGroupCard(): React.ReactElement {
  const { theme, fontSize } = useTheme();
  const create = useCreateGroup();
  const [name, setName] = useState('');
  const [visibility, setVisibility] = useState<Visibility>('public');
  const trimmed = name.trim();

  const handleCreate = () => {
    if (!trimmed) return;
    create.mutate({ name: trimmed, visibility }, { onSuccess: () => setName('') });
  };

  return (
    <Card>
      <Text variant="heading">Create a group</Text>
      <TextInput
        testID="group-name-input"
        value={name}
        onChangeText={setName}
        placeholder="e.g. Morning Focus Room"
        placeholderTextColor={theme.textSecondary}
        accessibilityLabel="Group name"
        maxLength={60}
        style={inputStyle(theme, fontSize)}
      />

      <View style={styles.segment}>
        {(Object.keys(VISIBILITY_LABELS) as Visibility[]).map((value) => (
          <Button
            key={value}
            label={VISIBILITY_LABELS[value]}
            variant={value === visibility ? 'primary' : 'ghost'}
            onPress={() => setVisibility(value)}
            accessibilityHint={`Set visibility to ${VISIBILITY_LABELS[value]}`}
            style={styles.segmentButton}
          />
        ))}
      </View>

      {create.isError ? (
        <Text variant="caption" color="danger" accessibilityRole="alert">
          {create.error instanceof Error ? create.error.message : 'Could not create the group.'}
        </Text>
      ) : null}

      <Button
        testID="create-group"
        label="Create group"
        onPress={handleCreate}
        disabled={!trimmed}
        loading={create.isPending}
      />
    </Card>
  );
}

function JoinByCodeCard(): React.ReactElement {
  const { theme, fontSize } = useTheme();
  const join = useJoinGroupByCode();
  const [code, setCode] = useState('');
  const trimmed = code.trim();

  const handleJoin = () => {
    if (!trimmed) return;
    join.mutate(trimmed, { onSuccess: () => setCode('') });
  };

  return (
    <Card>
      <Text variant="heading">Join with a code</Text>
      <TextInput
        testID="group-code-input"
        value={code}
        onChangeText={setCode}
        placeholder="Invite code"
        placeholderTextColor={theme.textSecondary}
        accessibilityLabel="Group invite code"
        autoCapitalize="characters"
        autoCorrect={false}
        maxLength={12}
        style={inputStyle(theme, fontSize)}
      />
      {join.isError ? (
        <Text variant="caption" color="danger" accessibilityRole="alert">
          {join.error instanceof Error ? join.error.message : 'That code did not work.'}
        </Text>
      ) : null}
      <Button
        testID="join-by-code"
        label="Join with code"
        variant="secondary"
        onPress={handleJoin}
        disabled={!trimmed}
        loading={join.isPending}
      />
    </Card>
  );
}

function DiscoverCard(): React.ReactElement {
  const { theme, fontSize } = useTheme();
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(query), 250);
    return () => clearTimeout(handle);
  }, [query]);

  const results = useDiscoverGroups(debounced);
  const active = debounced.trim().length >= 2;

  return (
    <Card testID="groups-discover">
      <Text variant="heading">Discover public groups</Text>
      <TextInput
        testID="group-discover-input"
        value={query}
        onChangeText={setQuery}
        placeholder="Search public groups"
        placeholderTextColor={theme.textSecondary}
        accessibilityLabel="Search public groups"
        autoCapitalize="none"
        autoCorrect={false}
        maxLength={60}
        style={inputStyle(theme, fontSize)}
      />

      {active && results.isLoading ? (
        <Text variant="caption" color="secondary">
          Searching…
        </Text>
      ) : null}

      {active && !results.isLoading && (results.data?.length ?? 0) === 0 ? (
        <Text variant="caption" color="secondary" testID="groups-discover-empty">
          No public groups found for “{debounced.trim()}”.
        </Text>
      ) : null}

      {results.data?.map((group) => (
        <GroupRow key={group.id} group={group} action={<DiscoverAction group={group} />} />
      ))}
    </Card>
  );
}

function GroupRow({
  group,
  action,
  subtitle,
}: {
  group: GroupSummary;
  action: React.ReactNode;
  subtitle?: string;
}): React.ReactElement {
  const meta =
    subtitle ??
    `${VISIBILITY_LABELS[group.visibility]} · ${group.member_count}/${group.max_members} members`;
  return (
    <View style={styles.row}>
      <View style={styles.flex}>
        <Text variant="body">{group.name}</Text>
        <Text variant="caption" color="secondary">
          {meta}
        </Text>
      </View>
      {action}
    </View>
  );
}

function InvitationActions({ invitationId }: { invitationId: string }): React.ReactElement {
  const accept = useAcceptGroupInvitation();
  const decline = useDeclineGroupInvitation();
  const busy = accept.isPending || decline.isPending;
  return (
    <View style={styles.actions}>
      <Button
        label="Decline"
        variant="ghost"
        onPress={() => decline.mutate(invitationId)}
        disabled={busy}
      />
      <Button label="Accept" onPress={() => accept.mutate(invitationId)} loading={accept.isPending} />
    </View>
  );
}

function LeaveAction({ groupId }: { groupId: string }): React.ReactElement {
  const leave = useLeaveGroup();
  return (
    <Button
      label="Leave"
      variant="ghost"
      onPress={() => leave.mutate(groupId)}
      loading={leave.isPending}
      accessibilityHint="Leaves this group"
    />
  );
}

function DiscoverAction({ group }: { group: GroupSummary }): React.ReactElement {
  const join = useJoinGroup();
  if (group.my_role) {
    return (
      <Text variant="label" color="secondary">
        Joined
      </Text>
    );
  }
  return (
    <Button
      label="Join"
      variant="secondary"
      onPress={() => join.mutate(group.id)}
      loading={join.isPending}
      accessibilityHint={`Join ${group.name}`}
    />
  );
}

function inputStyle(
  theme: ReturnType<typeof useTheme>['theme'],
  fontSize: ReturnType<typeof useTheme>['fontSize'],
) {
  return {
    minHeight: minTouchTarget,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surfaceMuted,
    color: theme.textPrimary,
    paddingHorizontal: spacing.md,
    fontSize: fontSize('body'),
  } as const;
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xxxl },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  actions: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  segment: { flexDirection: 'row', gap: spacing.sm },
  segmentButton: { flex: 1, paddingHorizontal: spacing.sm },
  flex: { flex: 1 },
});
