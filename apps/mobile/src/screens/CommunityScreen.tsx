/**
 * Community — a small, moderated feed of topic posts.
 *
 * Deliberately lightweight: post, react once, bookmark. Anything heavier (threads, rich
 * media) invites the moderation load a study app does not want. Reporting a post lives behind
 * the same report flow as the rest of the app; removing others' content is a moderator job,
 * not a user one.
 */

import React, { useState } from 'react';
import { ScrollView, StyleSheet, TextInput, View } from 'react-native';

import type { CommunityPost } from '@study-league/api-client';
import { minTouchTarget, radius, spacing } from '@study-league/design-tokens';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { ReportButton } from '@/components/ReportButton';
import { EmptyState, ErrorState, LoadingState } from '@/components/StateViews';
import { Text } from '@/components/Text';
import { useCreatePost, usePosts, useReactToPost, useToggleBookmark } from '@/features/api/queries';
import { useTheme } from '@/theme/ThemeProvider';

export function CommunityScreen(): React.ReactElement {
  const posts = usePosts();

  if (posts.isLoading && !posts.data) return <LoadingState label="Loading community…" />;
  if (posts.isError && !posts.data) {
    return <ErrorState testID="community-error" onRetry={() => void posts.refetch()} />;
  }

  const list = posts.data ?? [];

  return (
    <ScrollView testID="community-screen" contentContainerStyle={styles.content}>
      <NewPostCard />
      {list.length === 0 ? (
        <Card>
          <EmptyState title="No posts yet" description="Be the first to share something." />
        </Card>
      ) : (
        list.map((post) => <PostCard key={post.id} post={post} />)
      )}
    </ScrollView>
  );
}

function NewPostCard(): React.ReactElement {
  const { theme, fontSize } = useTheme();
  const create = useCreatePost();
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const canPost = title.trim().length >= 3 && body.trim().length > 0;

  const handlePost = () => {
    if (!canPost) return;
    create.mutate(
      { title: title.trim(), body: body.trim() },
      {
        onSuccess: () => {
          setTitle('');
          setBody('');
        },
      },
    );
  };

  return (
    <Card>
      <Text variant="heading">Share something</Text>
      <TextInput
        testID="post-title-input"
        value={title}
        onChangeText={setTitle}
        placeholder="Title"
        placeholderTextColor={theme.textSecondary}
        accessibilityLabel="Post title"
        maxLength={200}
        style={inputStyle(theme, fontSize)}
      />
      <TextInput
        testID="post-body-input"
        value={body}
        onChangeText={setBody}
        placeholder="What's on your mind?"
        placeholderTextColor={theme.textSecondary}
        accessibilityLabel="Post body"
        multiline
        maxLength={5000}
        style={[inputStyle(theme, fontSize), styles.multiline]}
      />
      <Button
        testID="create-post"
        label="Post"
        onPress={handlePost}
        disabled={!canPost}
        loading={create.isPending}
      />
    </Card>
  );
}

function PostCard({ post }: { post: CommunityPost }): React.ReactElement {
  const react = useReactToPost();
  const bookmark = useToggleBookmark();

  return (
    <Card testID={`post-${post.id}`}>
      <Text variant="caption" color="secondary">
        {post.topic} · @{post.author.username}
      </Text>
      <Text variant="heading">{post.title}</Text>
      <Text variant="body" color="secondary">
        {post.body}
      </Text>
      <View style={styles.actions}>
        <Button
          label={post.my_reaction ? '♥ Liked' : '♡ Like'}
          variant="ghost"
          onPress={() => react.mutate({ postId: post.id, emoji: 'like' })}
          accessibilityHint={`Like ${post.title}`}
        />
        <Text variant="caption" color="secondary" tabular>
          {post.reaction_count} · {post.comment_count} comments
        </Text>
        <View style={styles.spacer} />
        <Button
          label={post.bookmarked ? 'Saved' : 'Save'}
          variant="ghost"
          onPress={() => bookmark.mutate({ postId: post.id, bookmarked: post.bookmarked })}
          accessibilityHint={post.bookmarked ? 'Remove bookmark' : 'Bookmark this post'}
        />
        <ReportButton
          testID={`report-post-${post.id}`}
          subjectType="post"
          subjectId={post.id}
          subjectLabel="this post"
        />
      </View>
    </Card>
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
    paddingVertical: spacing.sm,
    fontSize: fontSize('body'),
  } as const;
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xxxl },
  multiline: { minHeight: 96, textAlignVertical: 'top' },
  actions: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: spacing.xs },
  spacer: { flex: 1 },
});
