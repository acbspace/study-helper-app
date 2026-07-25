/**
 * Study League design tokens.
 *
 * A single source of truth for colour, spacing, type, and motion, shared by the mobile app
 * and (later) the web dashboard. Screens never hardcode a hex value or a pixel number —
 * that is what keeps light/dark, dynamic type, and reduced motion working everywhere at
 * once.
 *
 * The palette is original to this product: a calm indigo for focus, warm amber for streaks,
 * and a restrained green reserved for verified time so "verified" reads instantly.
 */

export const palette = {
  indigo: {
    50: '#EEF1FE',
    100: '#D8DFFC',
    200: '#B4C0F8',
    300: '#8B9CF3',
    400: '#6B7FEE',
    500: '#4F6BED',
    600: '#3B52C7',
    700: '#2C3D96',
    800: '#1E2A69',
    900: '#141C46',
  },
  amber: {
    100: '#FDEBCF',
    300: '#F6C46A',
    500: '#E9A020',
    700: '#B0761040',
  },
  green: {
    100: '#D4F2E3',
    300: '#7ED4A8',
    500: '#37B27A',
    700: '#1F7C52',
  },
  coral: {
    100: '#FBDCD8',
    300: '#F2A198',
    500: '#E86A5B',
    700: '#B03D30',
  },
  violet: { 500: '#B565D8' },
  neutral: {
    0: '#FFFFFF',
    50: '#F7F8FA',
    100: '#EEF0F4',
    200: '#DFE3EA',
    300: '#C3C9D4',
    400: '#98A1B1',
    500: '#6B7688',
    600: '#4C5566',
    700: '#343C4A',
    800: '#212734',
    900: '#141822',
    950: '#0B0E15',
  },
} as const;

export interface Theme {
  background: string;
  surface: string;
  surfaceMuted: string;
  border: string;
  textPrimary: string;
  textSecondary: string;
  textInverse: string;
  accent: string;
  accentMuted: string;
  accentText: string;
  /** Reserved for timer-verified study time. */
  verified: string;
  verifiedMuted: string;
  /** Manually entered time — visible, but visually distinct from verified. */
  manual: string;
  streak: string;
  danger: string;
  dangerMuted: string;
  overlay: string;
}

/** Semantic colours. Components reference these, never `palette` directly. */
export const lightTheme: Theme = {
  background: palette.neutral[50],
  surface: palette.neutral[0],
  surfaceMuted: palette.neutral[100],
  border: palette.neutral[200],
  textPrimary: palette.neutral[900],
  textSecondary: palette.neutral[500],
  textInverse: palette.neutral[0],
  accent: palette.indigo[500],
  accentMuted: palette.indigo[100],
  accentText: palette.indigo[700],
  /** Reserved for timer-verified study time. */
  verified: palette.green[500],
  verifiedMuted: palette.green[100],
  /** Manually entered time — visible, but visually distinct from verified. */
  manual: palette.neutral[400],
  streak: palette.amber[500],
  danger: palette.coral[500],
  dangerMuted: palette.coral[100],
  overlay: 'rgba(11, 14, 21, 0.45)',
} as const;

export const darkTheme: Theme = {
  background: palette.neutral[950],
  surface: palette.neutral[900],
  surfaceMuted: palette.neutral[800],
  border: palette.neutral[700],
  textPrimary: palette.neutral[50],
  textSecondary: palette.neutral[400],
  textInverse: palette.neutral[950],
  accent: palette.indigo[400],
  accentMuted: palette.indigo[800],
  accentText: palette.indigo[100],
  verified: palette.green[300],
  verifiedMuted: palette.green[700],
  manual: palette.neutral[500],
  streak: palette.amber[300],
  danger: palette.coral[300],
  dangerMuted: palette.coral[700],
  overlay: 'rgba(0, 0, 0, 0.6)',
} as const;

export type ThemeName = 'light' | 'dark';

/** 4pt base scale. */
export const spacing = {
  xxs: 2,
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
} as const;

export const radius = {
  sm: 6,
  md: 10,
  lg: 16,
  xl: 24,
  pill: 999,
} as const;

/**
 * Type scale. `size` values are scaled by the OS font-size setting at render time
 * (see useScaledFontSize), so these are base sizes rather than fixed ones.
 */
export const typography = {
  display: { size: 40, lineHeight: 46, weight: '700' },
  title: { size: 26, lineHeight: 32, weight: '700' },
  heading: { size: 19, lineHeight: 25, weight: '600' },
  body: { size: 16, lineHeight: 23, weight: '400' },
  label: { size: 14, lineHeight: 19, weight: '500' },
  caption: { size: 12, lineHeight: 16, weight: '400' },
  /** Tabular figures keep the timer from jittering as digits change. */
  timer: { size: 60, lineHeight: 66, weight: '300' },
} as const;

export type TypographyVariant = keyof typeof typography;

/**
 * Minimum touch target (points). Matches the stricter of the iOS (44) and Android (48)
 * guidelines so every control is comfortable on both.
 */
export const minTouchTarget = 48;

export const motion = {
  fast: 120,
  base: 200,
  slow: 320,
} as const;

/** Default subject colours offered in the subject editor. */
export const subjectColors = [
  palette.indigo[500],
  palette.coral[500],
  palette.green[500],
  palette.amber[500],
  palette.violet[500],
  palette.neutral[500],
] as const;
