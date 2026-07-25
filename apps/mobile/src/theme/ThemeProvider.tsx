/**
 * Theme and accessibility context.
 *
 * Colour scheme follows the OS. Font sizes scale with the user's chosen text size, and
 * animation is suppressed when the OS asks for reduced motion — handled here once so no
 * screen has to remember.
 */

import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { AccessibilityInfo, useColorScheme, useWindowDimensions } from 'react-native';

import {
  darkTheme,
  lightTheme,
  type Theme,
  type ThemeName,
  typography,
  type TypographyVariant,
} from '@study-league/design-tokens';

interface ThemeContextValue {
  theme: Theme;
  name: ThemeName;
  reduceMotion: boolean;
  /** Scale a token font size by the OS text-size preference, within safe bounds. */
  fontSize: (variant: TypographyVariant) => number;
  lineHeight: (variant: TypographyVariant) => number;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

/**
 * Clamp text scaling. Unbounded scaling breaks the timer layout at extreme settings;
 * clamping keeps large-text users supported without an unusable screen.
 */
const MIN_SCALE = 0.85;
const MAX_SCALE = 1.6;

export function ThemeProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  const colorScheme = useColorScheme();
  const { fontScale } = useWindowDimensions();
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    let cancelled = false;
    AccessibilityInfo.isReduceMotionEnabled()
      .then((enabled) => {
        if (!cancelled) setReduceMotion(enabled);
      })
      .catch(() => {
        // Preference unavailable on this platform; motion stays enabled.
      });

    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduceMotion);
    return () => {
      cancelled = true;
      subscription.remove();
    };
  }, []);

  const value = useMemo<ThemeContextValue>(() => {
    const name: ThemeName = colorScheme === 'dark' ? 'dark' : 'light';
    const scale = Math.min(Math.max(fontScale, MIN_SCALE), MAX_SCALE);
    return {
      theme: name === 'dark' ? darkTheme : lightTheme,
      name,
      reduceMotion,
      fontSize: (variant) => Math.round(typography[variant].size * scale),
      lineHeight: (variant) => Math.round(typography[variant].lineHeight * scale),
    };
  }, [colorScheme, fontScale, reduceMotion]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used inside a ThemeProvider.');
  }
  return context;
}
