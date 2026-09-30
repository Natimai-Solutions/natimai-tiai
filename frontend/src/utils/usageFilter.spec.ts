import { describe, expect, it } from 'vitest';
import {
  hoursLabel,
  parseHours,
  usageFilterLabel,
  usagePresetBounds,
  usagePresetOf,
  usageSettingsError,
} from './usageFilter';

const T = { low: 10, high: 30 };

describe('usagePresetBounds', () => {
  it('draws each preset from the thresholds', () => {
    expect(usagePresetBounds('low', T)).toEqual({ below: 10, above: null });
    expect(usagePresetBounds('mid', T)).toEqual({ below: 30, above: 10 });
    expect(usagePresetBounds('high', T)).toEqual({ below: null, above: 30 });
  });
});

describe('usagePresetOf', () => {
  it('recognises the bounds a dashboard card writes', () => {
    expect(usagePresetOf({ below: 10, above: null }, T)).toBe('low');
    expect(usagePresetOf({ below: 30, above: 10 }, T)).toBe('mid');
    expect(usagePresetOf({ below: null, above: 30 }, T)).toBe('high');
  });

  it('reads no bound as no filter, and any other pair as custom', () => {
    expect(usagePresetOf({ below: null, above: null }, T)).toBeNull();
    expect(usagePresetOf({ below: 12, above: null }, T)).toBe('custom');
    expect(usagePresetOf({ below: 30, above: 5 }, T)).toBe('custom');
  });

  it('calls bounds custom until the thresholds are known', () => {
    expect(usagePresetOf({ below: 10, above: null }, null)).toBe('custom');
    expect(usagePresetOf({ below: null, above: null }, null)).toBeNull();
  });
});

describe('usageFilterLabel', () => {
  it('names one bound, both, and the window', () => {
    expect(usageFilterLabel({ below: 10, above: null }, 7)).toBe('Allumés moins de 10 h sur 7 j');
    expect(usageFilterLabel({ below: null, above: 30 }, 7)).toBe('Allumés plus de 30 h sur 7 j');
    expect(usageFilterLabel({ below: 30, above: 10 }, null)).toBe('Allumés entre 10 h et 30 h');
  });
});

describe('hoursLabel', () => {
  it('writes hours the French way, to the tenth at most', () => {
    expect(hoursLabel(12.4)).toBe('12,4 h');
    expect(hoursLabel(0)).toBe('0 h');
    expect(hoursLabel(31)).toBe('31 h');
  });
});

describe('parseHours', () => {
  it('accepts numbers, typed text and a French decimal comma', () => {
    expect(parseHours(7)).toBe(7);
    expect(parseHours('7.5')).toBe(7.5);
    expect(parseHours('7,5')).toBe(7.5);
    expect(parseHours('0')).toBe(0);
  });

  it('reads empty, negative and garbage as no bound', () => {
    expect(parseHours('')).toBeNull();
    expect(parseHours(null)).toBeNull();
    expect(parseHours(undefined)).toBeNull();
    expect(parseHours('-3')).toBeNull();
    expect(parseHours('dix')).toBeNull();
  });
});

describe('usageSettingsError', () => {
  it('accepts a set that holds together', () => {
    expect(usageSettingsError(7, 10, 30)).toBeNull();
    expect(usageSettingsError(7, 0, 168)).toBeNull();
  });

  it('refuses what the server would refuse', () => {
    expect(usageSettingsError(0, 10, 30)).toMatch(/fenêtre/);
    expect(usageSettingsError(91, 10, 30)).toMatch(/fenêtre/);
    expect(usageSettingsError(7, 30, 30)).toMatch(/sous le seuil/);
    expect(usageSettingsError(7, 10, 200)).toMatch(/168 heures/);
  });

  it('refuses an emptied or fractional box', () => {
    expect(usageSettingsError(7, '', 30)).toMatch(/peu utilisé/);
    expect(usageSettingsError(7, 10, 30.5)).toMatch(/toujours allumé/);
    expect(usageSettingsError(2.5, 10, 30)).toMatch(/fenêtre/);
  });
});
