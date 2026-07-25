/**
 * Button primitive.
 *
 * Enforces the minimum touch target, exposes the correct accessibility role and state,
 * and prevents double submission while an async action is in flight.
 */

import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  type StyleProp,
  StyleSheet,
  type ViewStyle,
} from 'react-native';

import { minTouchTarget, radius, spacing } from '@study-league/design-tokens';

import { useTheme } from '@/theme/ThemeProvider';

import { Text } from './Text';

export interface ButtonProps {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'medium' | 'large';
  disabled?: boolean;
  loading?: boolean;
  accessibilityHint?: string;
  testID?: string;
  style?: StyleProp<ViewStyle>;
}

export function Button({
  label,
  onPress,
  variant = 'primary',
  size = 'medium',
  disabled = false,
  loading = false,
  accessibilityHint,
  testID,
  style,
}: ButtonProps): React.ReactElement {
  const { theme } = useTheme();
  const isDisabled = disabled || loading;

  const backgrounds: Record<NonNullable<ButtonProps['variant']>, string> = {
    primary: theme.accent,
    secondary: theme.surfaceMuted,
    ghost: 'transparent',
    danger: theme.danger,
  };
  const labelColors: Record<NonNullable<ButtonProps['variant']>, 'inverse' | 'primary' | 'accent'> =
    {
      primary: 'inverse',
      secondary: 'primary',
      ghost: 'accent',
      danger: 'inverse',
    };

  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      disabled={isDisabled}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={accessibilityHint}
      // Communicates both states to screen readers, so a spinner is not silent.
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      style={({ pressed }) => [
        styles.base,
        {
          backgroundColor: backgrounds[variant],
          borderColor: variant === 'ghost' ? theme.border : 'transparent',
          borderWidth: variant === 'ghost' ? 1 : 0,
          minHeight: size === 'large' ? 56 : minTouchTarget,
          opacity: isDisabled ? 0.5 : pressed ? 0.85 : 1,
        },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator
          color={variant === 'primary' || variant === 'danger' ? theme.textInverse : theme.accent}
        />
      ) : (
        <Text
          variant={size === 'large' ? 'heading' : 'label'}
          color={labelColors[variant]}
          align="center"
        >
          {label}
        </Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.md,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
  },
});
