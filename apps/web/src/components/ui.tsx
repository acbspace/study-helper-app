/**
 * A tiny set of styled primitives built directly on the shared design tokens, so the web
 * dashboard reads as the same product as the mobile app without pulling in a UI framework.
 */

import type { CSSProperties, ReactElement, ReactNode } from 'react';

import { radius, spacing, theme } from '@/theme';

export function Card({
  children,
  style,
  testId,
}: {
  children: ReactNode;
  style?: CSSProperties;
  testId?: string;
}): ReactElement {
  return (
    <section
      data-testid={testId}
      style={{
        background: theme.surface,
        border: `1px solid ${theme.border}`,
        borderRadius: radius.lg,
        padding: spacing.lg,
        display: 'flex',
        flexDirection: 'column',
        gap: spacing.sm,
        ...style,
      }}
    >
      {children}
    </section>
  );
}

export function StatTile({
  label,
  value,
  accent,
  testId,
}: {
  label: string;
  value: string;
  accent?: boolean;
  testId?: string;
}): ReactElement {
  return (
    <Card testId={testId} style={{ gap: spacing.xs }}>
      <span style={{ color: theme.textSecondary, fontSize: 13 }}>{label}</span>
      <span
        style={{
          color: accent ? theme.accentText : theme.textPrimary,
          fontSize: 28,
          fontWeight: 700,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </span>
    </Card>
  );
}

export function Button({
  label,
  onClick,
  type = 'button',
  disabled,
  variant = 'primary',
}: {
  label: string;
  onClick?: () => void;
  type?: 'button' | 'submit';
  disabled?: boolean;
  variant?: 'primary' | 'ghost';
}): ReactElement {
  const primary = variant === 'primary';
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={{
        background: primary ? theme.accent : 'transparent',
        color: primary ? theme.textInverse : theme.accentText,
        border: primary ? 'none' : `1px solid ${theme.border}`,
        borderRadius: radius.md,
        padding: `${spacing.sm}px ${spacing.lg}px`,
        fontSize: 15,
        fontWeight: 600,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {label}
    </button>
  );
}

export function Meter({ progress, color }: { progress: number; color?: string }): ReactElement {
  const clamped = Math.max(0, Math.min(1, progress));
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(clamped * 100)}
      style={{
        background: theme.surfaceMuted,
        borderRadius: radius.pill,
        height: 8,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          background: color ?? theme.accent,
          width: `${clamped * 100}%`,
          height: '100%',
        }}
      />
    </div>
  );
}

export function Spinner({ label = 'Loading…' }: { label?: string }): ReactElement {
  return (
    <div
      role="status"
      style={{ color: theme.textSecondary, padding: spacing.xl, textAlign: 'center' }}
    >
      {label}
    </div>
  );
}
