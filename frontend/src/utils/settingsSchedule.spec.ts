import { describe, expect, it } from 'vitest';

import {
  WEEKDAYS_FR,
  digestSummary,
  isAgentVersion,
  localTimeOfUtcHour,
  reminderSummary,
} from './settingsSchedule';

// A Thursday, outside any daylight saving change in Europe.
const REF = new Date(Date.UTC(2026, 9, 1, 12));

describe('localTimeOfUtcHour', () => {
  it('reads a UTC hour on the reader clock', () => {
    expect(localTimeOfUtcHour(18, 'Pacific/Tahiti', REF)).toBe('08:00');
    expect(localTimeOfUtcHour(18, 'UTC', REF)).toBe('18:00');
  });

  it('follows daylight saving time around the reference date', () => {
    const summer = new Date(Date.UTC(2026, 6, 1));
    const winter = new Date(Date.UTC(2026, 11, 1));
    expect(localTimeOfUtcHour(6, 'Europe/Paris', summer)).toBe('08:00');
    expect(localTimeOfUtcHour(6, 'Europe/Paris', winter)).toBe('07:00');
  });
});

describe('digestSummary', () => {
  it('says when the digest lands, and in which zone', () => {
    expect(digestSummary(18, 'Pacific/Tahiti', REF)).toBe('chaque jour à 08:00 (Pacific/Tahiti)');
  });
});

describe('reminderSummary', () => {
  it('keeps the weekday when the local date is the UTC one', () => {
    expect(reminderSummary(0, 18, 'Pacific/Tahiti', REF)).toBe('le lundi à 08:00 (Pacific/Tahiti)');
  });

  it('moves to the local weekday when the hour crosses midnight', () => {
    // Monday 02:00 UTC is Sunday 16:00 in Tahiti.
    expect(reminderSummary(0, 2, 'Pacific/Tahiti', REF)).toBe(
      'le dimanche à 16:00 (Pacific/Tahiti)',
    );
  });

  it('names every weekday the server can store', () => {
    expect(WEEKDAYS_FR).toHaveLength(7);
    WEEKDAYS_FR.forEach((day, i) => {
      expect(reminderSummary(i, 12, 'UTC', REF)).toBe(`le ${day} à 12:00 (UTC)`);
    });
  });
});

describe('isAgentVersion', () => {
  it.each(['', '1', '1.0.2', 'v1.0.2', '1.1.0-rc.1', '0.0.0-dev.abc123', ' 1.0.2 '])(
    'accepts %j',
    (v) => expect(isAgentVersion(v)).toBe(true),
  );

  it.each(['latest', '1..2', 'v', '1.0.2 beta'])('refuses %j', (v) =>
    expect(isAgentVersion(v)).toBe(false),
  );
});
