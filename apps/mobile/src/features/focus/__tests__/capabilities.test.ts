/**
 * Focus-protection capabilities must be reported honestly: everything unavailable in this
 * build, and each with a human reason (PRD §5.3 — unsupported is disabled, never faked).
 */

import { resolveFocusCapabilities } from '../capabilities';

describe('resolveFocusCapabilities', () => {
  it('reports every capability as unavailable, with a reason', () => {
    const capabilities = resolveFocusCapabilities();

    expect(capabilities.map((c) => c.id)).toEqual([
      'app_blocking',
      'distraction_alerts',
      'background_detection',
    ]);
    expect(capabilities.every((c) => c.available === false)).toBe(true);
    expect(capabilities.every((c) => c.reason.length > 0)).toBe(true);
  });
});
