/**
 * Subject management: create, recolour, and archive.
 *
 * Subjects are archived rather than deleted so historical statistics stay readable.
 */

import React, { useState } from 'react';
import { ScrollView, StyleSheet, TextInput, View } from 'react-native';

import { minTouchTarget, radius, spacing, subjectColors } from '@study-league/design-tokens';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { EmptyState, ErrorState, LoadingState } from '@/components/StateViews';
import { Text } from '@/components/Text';
import { useCreateSubject, useSubjects, useUpdateSubject } from '@/features/api/queries';
import { useTheme } from '@/theme/ThemeProvider';

export default function SubjectsScreen(): React.ReactElement {
  const { theme, fontSize } = useTheme();
  const subjects = useSubjects();
  const createSubject = useCreateSubject();
  const updateSubject = useUpdateSubject();

  const [name, setName] = useState('');
  const [color, setColor] = useState<string>(subjectColors[0]);

  const trimmed = name.trim();

  const handleCreate = () => {
    if (!trimmed) return;
    createSubject.mutate({ name: trimmed, color_hex: color }, { onSuccess: () => setName('') });
  };

  if (subjects.isLoading && !subjects.data) return <LoadingState label="Loading subjects…" />;
  if (subjects.isError && !subjects.data) {
    return <ErrorState onRetry={() => void subjects.refetch()} />;
  }

  return (
    <ScrollView testID="subjects-screen" contentContainerStyle={styles.content}>
      <Card>
        <Text variant="heading">New subject</Text>
        <TextInput
          testID="subject-name-input"
          value={name}
          onChangeText={setName}
          placeholder="e.g. Organic Chemistry"
          placeholderTextColor={theme.textSecondary}
          accessibilityLabel="Subject name"
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

        <Text variant="label">Colour</Text>
        <View style={styles.swatchRow}>
          {subjectColors.map((option) => (
            <Button
              key={option}
              label={option === color ? '✓' : ' '}
              variant="ghost"
              onPress={() => setColor(option)}
              accessibilityHint={`Use the colour ${option}`}
              style={{
                backgroundColor: option,
                minWidth: minTouchTarget,
                borderWidth: option === color ? 3 : 0,
                borderColor: theme.textPrimary,
              }}
            />
          ))}
        </View>

        {createSubject.isError ? (
          <Text variant="caption" color="danger" accessibilityRole="alert">
            {createSubject.error instanceof Error
              ? createSubject.error.message
              : 'Could not create the subject.'}
          </Text>
        ) : null}

        <Button
          testID="create-subject"
          label="Add subject"
          onPress={handleCreate}
          disabled={!trimmed}
          loading={createSubject.isPending}
        />
      </Card>

      <Card>
        <Text variant="heading">Your subjects</Text>
        {(subjects.data?.length ?? 0) === 0 ? (
          <EmptyState
            title="No subjects yet"
            description="Add one above to start tracking where your time goes."
          />
        ) : (
          subjects.data?.map((subject) => (
            <View key={subject.id} style={styles.subjectRow}>
              <View style={[styles.swatch, { backgroundColor: subject.color_hex }]} />
              <Text variant="body" style={styles.flex}>
                {subject.name}
              </Text>
              <Button
                label="Archive"
                variant="ghost"
                onPress={() =>
                  updateSubject.mutate({
                    subjectId: subject.id,
                    changes: { is_archived: true },
                  })
                }
                accessibilityHint={`Archives ${subject.name}. Past study time is kept.`}
              />
            </View>
          ))
        )}
      </Card>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.lg },
  swatchRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  subjectRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  swatch: { width: 14, height: 14, borderRadius: 7 },
  flex: { flex: 1 },
});
