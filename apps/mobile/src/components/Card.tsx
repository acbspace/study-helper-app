import React from 'react';
import { type StyleProp, StyleSheet, View, type ViewStyle } from 'react-native';

import { radius, spacing } from '@study-league/design-tokens';

import { useTheme } from '@/theme/ThemeProvider';

export function Card({
  children,
  style,
  testID,
  accessibilityLabel,
}: {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  testID?: string;
  accessibilityLabel?: string;
}): React.ReactElement {
  const { theme } = useTheme();
  return (
    <View
      testID={testID}
      accessible={accessibilityLabel !== undefined}
      accessibilityLabel={accessibilityLabel}
      style={[styles.card, { backgroundColor: theme.surface, borderColor: theme.border }, style]}
    >
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: spacing.lg,
    gap: spacing.md,
  },
});
