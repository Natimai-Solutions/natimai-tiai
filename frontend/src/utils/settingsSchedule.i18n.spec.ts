import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import { intFieldError } from './numberField';
import { WEEKDAYS_FR, digestSummary, reminderSummary, weekdayName } from './settingsSchedule';

// A Wednesday in July: Tahiti has no daylight saving time.
const REF = new Date('2026-07-15T12:00:00Z');

afterEach(() => setLocale('fr'));

describe('the mail schedule in both languages', () => {
  it('names the days as the server writes them, in French', () => {
    WEEKDAYS_FR.forEach((day, i) => expect(weekdayName(i)).toBe(day));
  });

  it('names the days in English', () => {
    setLocale('en');
    expect([0, 1, 2, 3, 4, 5, 6].map(weekdayName)).toEqual([
      'Monday',
      'Tuesday',
      'Wednesday',
      'Thursday',
      'Friday',
      'Saturday',
      'Sunday',
    ]);
  });

  it('says when the mail lands, in English', () => {
    setLocale('en');
    expect(digestSummary(18, 'Pacific/Tahiti', REF)).toBe('every day at 08:00 (Pacific/Tahiti)');
    // Monday 02:00 UTC is Sunday 16:00 in Tahiti.
    expect(reminderSummary(0, 2, 'Pacific/Tahiti', REF)).toBe(
      'on Sunday at 16:00 (Pacific/Tahiti)',
    );
  });
});

describe('intFieldError in English', () => {
  it('says what is wrong', () => {
    setLocale('en');
    expect(intFieldError('', 0, 365)).toBe('Value required');
    expect(intFieldError(2.5, 0, 365)).toBe('A whole number');
    expect(intFieldError(0, 1, 3650)).toBe('Between 1 and 3650');
    expect(intFieldError(5, 1, 3650)).toBeNull();
  });
});
