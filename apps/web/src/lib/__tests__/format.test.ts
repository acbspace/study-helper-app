import { describe, expect, it } from 'vitest';

import { formatDuration, formatPercent } from '../format';

describe('formatDuration', () => {
  it('formats hours and minutes', () => {
    expect(formatDuration(2 * 3600 + 15 * 60)).toBe('2h 15m');
  });

  it('drops the hours when under an hour', () => {
    expect(formatDuration(45 * 60)).toBe('45m');
  });

  it('drops the minutes on a whole hour', () => {
    expect(formatDuration(3600)).toBe('1h');
  });

  it('never goes negative', () => {
    expect(formatDuration(-100)).toBe('0m');
  });
});

describe('formatPercent', () => {
  it('rounds and clamps', () => {
    expect(formatPercent(0.756)).toBe('76%');
    expect(formatPercent(1.5)).toBe('100%');
    expect(formatPercent(-1)).toBe('0%');
  });
});
