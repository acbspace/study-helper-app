/**
 * Typography primitive.
 *
 * Every piece of text in the app goes through here so font scaling, colour, and contrast
 * are consistent and accessible by default rather than by remembering.
 */

import React from 'react';
import { Text as RNText, type TextProps as RNTextProps, type TextStyle } from 'react-native';

import { typography, type TypographyVariant } from '@study-league/design-tokens';

import { useTheme } from '@/theme/ThemeProvider';

export interface TextProps extends RNTextProps {
  variant?: TypographyVariant;
  color?: 'primary' | 'secondary' | 'accent' | 'verified' | 'manual' | 'danger' | 'inverse';
  align?: TextStyle['textAlign'];
  weight?: TextStyle['fontWeight'];
  /** Tabular figures — keeps numbers from shifting as digits change. */
  tabular?: boolean;
}

export function Text({
  variant = 'body',
  color = 'primary',
  align,
  weight,
  tabular = false,
  style,
  children,
  ...rest
}: TextProps): React.ReactElement {
  const { theme, fontSize, lineHeight } = useTheme();

  const colors: Record<NonNullable<TextProps['color']>, string> = {
    primary: theme.textPrimary,
    secondary: theme.textSecondary,
    accent: theme.accentText,
    verified: theme.verified,
    manual: theme.manual,
    danger: theme.danger,
    inverse: theme.textInverse,
  };

  return (
    <RNText
      style={[
        {
          fontSize: fontSize(variant),
          lineHeight: lineHeight(variant),
          fontWeight: weight ?? (typography[variant].weight as TextStyle['fontWeight']),
          color: colors[color],
          textAlign: align,
          ...(tabular ? { fontVariant: ['tabular-nums'] as TextStyle['fontVariant'] } : {}),
        },
        style,
      ]}
      {...rest}
    >
      {children}
    </RNText>
  );
}
