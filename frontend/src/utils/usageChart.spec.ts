import { describe, expect, it } from 'vitest';
import type { MachineUsage } from 'src/services/machines';
import { countedFrom, localDate, measuredSummary, usageBars } from './usageChart';

function usage(overrides: Partial<MachineUsage> = {}): MachineUsage {
  return {
    days: 4,
    tz: 'UTC',
    total_hours: 20,
    daily: [
      { date: '2026-09-26', hours: 0 },
      { date: '2026-09-27', hours: 6 },
      { date: '2026-09-28', hours: 24 },
      { date: '2026-09-29', hours: 0 },
    ],
    // Noon, so the local date is the same in any zone the tests run in.
    first_seen: '2026-01-01T12:00:00Z',
    usage_since: '2026-09-27T12:00:00Z',
    ...overrides,
  };
}

describe('countedFrom', () => {
  it('starts at the later of enrolment and the first count', () => {
    expect(countedFrom(usage())).toBe('2026-09-27');
    expect(countedFrom(usage({ first_seen: '2026-09-28T12:00:00Z' }))).toBe('2026-09-28');
  });

  it('is null while nothing has been counted', () => {
    expect(countedFrom(usage({ usage_since: null }))).toBeNull();
  });
});

describe('usageBars', () => {
  it('scales on a full day and marks the unmeasured days', () => {
    const bars = usageBars(usage());
    expect(bars.map((b) => b.percent)).toEqual([0, 25, 100, 0]);
    expect(bars.map((b) => b.counted)).toEqual([false, true, true, true]);
  });

  it('flags the weekend', () => {
    // 26/09/2026 is a Saturday, 27 a Sunday.
    expect(usageBars(usage()).map((b) => b.weekend)).toEqual([true, true, false, false]);
  });

  it('labels days in French', () => {
    expect(usageBars(usage())[2]!.label).toBe('lun. 28/09');
  });

  it('measures nothing before the first count', () => {
    expect(usageBars(usage({ usage_since: null })).every((b) => !b.counted)).toBe(true);
  });
});

describe('measuredSummary', () => {
  it('sums the measured days only', () => {
    expect(measuredSummary(usageBars(usage()))).toEqual({ hours: 30, days: 3 });
  });
});

describe('localDate', () => {
  it('formats a day as YYYY-MM-DD', () => {
    expect(localDate('2026-09-28T12:00:00Z')).toBe('2026-09-28');
  });
});
