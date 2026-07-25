/**
 * Report a user, group, post, or comment.
 *
 * The moderation pipeline — `POST /reports`, the admin queue, audit-logged resolutions — has
 * been complete server-side since M2 with no way for anyone to file a report, so the queue
 * could never have anything in it. This is the entrance.
 *
 * One component rather than a per-surface implementation, because the server treats every
 * subject type identically and the UI should not invent differences that do not exist.
 */

import React, { useState } from 'react';
import { Modal, StyleSheet, TextInput, View } from 'react-native';

import { ApiError, type ReportSubjectType } from '@study-league/api-client';
import { minTouchTarget, radius, spacing } from '@study-league/design-tokens';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Text } from '@/components/Text';
import { useReportContent } from '@/features/api/queries';
import { useTheme } from '@/theme/ThemeProvider';

/** Matches the server's 3–1000 character rule, so a rejected report is caught before sending. */
const MIN_REASON = 3;
const MAX_REASON = 1000;

export function ReportButton({
  subjectType,
  subjectId,
  subjectLabel,
  testID,
}: {
  subjectType: ReportSubjectType;
  subjectId: string;
  /** What the user is reporting, used in the confirmation copy. */
  subjectLabel: string;
  testID?: string;
}): React.ReactElement {
  const { theme, fontSize } = useTheme();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [done, setDone] = useState(false);
  const report = useReportContent();

  const trimmed = reason.trim();

  const close = () => {
    setOpen(false);
    setReason('');
    setDone(false);
    report.reset();
  };

  const submit = () => {
    report.mutate(
      { subject_type: subjectType, subject_id: subjectId, reason: trimmed },
      { onSuccess: () => setDone(true) },
    );
  };

  return (
    <>
      <Button
        testID={testID ?? 'report-open'}
        label="Report"
        variant="ghost"
        onPress={() => setOpen(true)}
        accessibilityHint={`Reports ${subjectLabel} to the moderators.`}
      />

      <Modal
        visible={open}
        animationType="slide"
        transparent
        onRequestClose={close}
        accessibilityViewIsModal
      >
        <View style={[styles.backdrop, { backgroundColor: theme.background }]}>
          <Card testID="report-sheet">
            <Text variant="heading">Report {subjectLabel}</Text>

            {done ? (
              <>
                <Text variant="body" color="secondary" testID="report-done">
                  Thanks — a moderator will review this. We will not tell them who reported it.
                </Text>
                <Button label="Close" onPress={close} />
              </>
            ) : (
              <>
                <Text variant="caption" color="secondary">
                  Tell us what is wrong. Reports are reviewed by a moderator, and the person you
                  report is never told who filed it.
                </Text>

                <TextInput
                  testID="report-reason"
                  value={reason}
                  onChangeText={setReason}
                  placeholder="What is happening?"
                  placeholderTextColor={theme.textSecondary}
                  accessibilityLabel="Reason for reporting"
                  multiline
                  maxLength={MAX_REASON}
                  style={{
                    minHeight: minTouchTarget * 2,
                    borderRadius: radius.md,
                    borderWidth: 1,
                    borderColor: theme.border,
                    backgroundColor: theme.surfaceMuted,
                    color: theme.textPrimary,
                    padding: spacing.md,
                    fontSize: fontSize('body'),
                  }}
                />

                {report.isError ? (
                  <Text variant="caption" color="danger" accessibilityRole="alert">
                    {describeError(report.error)}
                  </Text>
                ) : null}

                <View style={styles.actions}>
                  <Button label="Cancel" variant="ghost" onPress={close} style={styles.action} />
                  <Button
                    testID="report-submit"
                    label="Send report"
                    onPress={submit}
                    disabled={trimmed.length < MIN_REASON}
                    loading={report.isPending}
                    style={styles.action}
                  />
                </View>
              </>
            )}
          </Card>
        </View>
      </Modal>
    </>
  );
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'report_exists') {
      return 'You have already reported this. A moderator is looking at it.';
    }
    if (error.code === 'cannot_report_self') return 'You cannot report yourself.';
    if (error.code === 'rate_limited') {
      return 'Too many reports just now. Please try again shortly.';
    }
    if (error.code === 'network_error') {
      return 'Could not reach the server. Your report was not sent.';
    }
    return error.message;
  }
  return 'Could not send the report. Please try again.';
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'center', padding: spacing.lg },
  actions: { flexDirection: 'row', gap: spacing.md },
  action: { flex: 1 },
});
