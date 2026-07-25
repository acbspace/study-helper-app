/**
 * Focus-protection capabilities, described honestly.
 *
 * Blocking distracting apps needs native OS integration — Screen Time (iOS) and UsageStats /
 * accessibility services (Android) — that this build does not ship. The product rule (PRD
 * §5.3) is that an unsupported capability must be *visibly disabled and explained*, never
 * simulated into looking like it works. So this module reports the truth: nothing is
 * available yet, and each capability carries the reason.
 *
 * When the native modules land, only `resolveFocusCapabilities` changes; every screen that
 * reads it keeps working.
 */

import { Platform } from 'react-native';

export type FocusCapabilityId = 'app_blocking' | 'distraction_alerts' | 'background_detection';

export interface FocusCapability {
  id: FocusCapabilityId;
  label: string;
  available: boolean;
  /** Shown to the user when unavailable, so a disabled control is never a mystery. */
  reason: string;
}

const PLATFORM_NAME: Record<string, string> = {
  ios: 'iOS',
  android: 'Android',
  web: 'the web',
};

export function resolveFocusCapabilities(): FocusCapability[] {
  const platform = PLATFORM_NAME[Platform.OS] ?? 'this platform';
  const pending = (label: string, requirement: string): string =>
    `${label} needs ${requirement} on ${platform}, which this build does not include yet.`;

  return [
    {
      id: 'app_blocking',
      label: 'Block distracting apps',
      available: false,
      reason: pending('App blocking', "the OS Screen Time / UsageStats permission"),
    },
    {
      id: 'distraction_alerts',
      label: 'Alert when you leave the app',
      available: false,
      reason: pending('Distraction alerts', 'a background monitoring service'),
    },
    {
      id: 'background_detection',
      label: 'Pause on app switch',
      available: false,
      reason: pending('Background detection', 'a native lifecycle module'),
    },
  ];
}
