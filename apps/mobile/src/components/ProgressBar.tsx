/**
 * Goal progress indicator.
 *
 * Exposes the real numbers to assistive technology rather than only a coloured bar, so
 * progress is legible without sight and without relying on colour alone.
 */

import React from 'react';
import { StyleSheet, View } from 'react-native';

import { radius } from '@study-league/design-tokens';

import { useTheme } from '@/theme/ThemeProvider';

export interface ProgressBarProps {
  /** 0–1; values outside the range are clamped. */
  progress: number;
  color?: string;
  height?: number;
  accessibilityLabel: string;
  testID?: string;
}

export function ProgressBar({
  progress,
  color,
  height = 10,
  accessibilityLabel,
  testID,
}: ProgressBarProps): React.ReactElement {
  const { theme } = useTheme();
  const clamped = Math.min(Math.max(progress, 0), 1);
  const percent = Math.round(clamped * 100);

  return (
    <View
      testID={testID}
      accessible
      accessibilityRole="progressbar"
      accessibilityLabel={accessibilityLabel}
      accessibilityValue={{ min: 0, max: 100, now: percent, text: `${percent} percent` }}
      style={[styles.track, { backgroundColor: theme.surfaceMuted, height, borderRadius: height }]}
    >
      <View
        style={{
          width: `${percent}%`,
          height: '100%',
          backgroundColor: color ?? theme.accent,
          borderRadius: radius.pill,
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  track: {
    width: '100%',
    overflow: 'hidden',
  },
});
