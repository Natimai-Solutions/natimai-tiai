import { intlTag, t } from 'src/i18n';
/**
 * The machine list's « Utilisation » filter, as pure functions.
 *
 * The URL speaks in two bounds — `usage_hours_below`, `usage_hours_above` —
 * because that is what the server filters on and what a pasted link must
 * carry. The dropdown speaks in the questions an administrator asks, drawn
 * from the console's two thresholds: « peu utilisés », « entre les deux »,
 * « toujours allumés », or any other pair of bounds. These functions translate
 * between the two, so a dashboard card that writes `usage_hours_below=10`
 * lands on a list whose dropdown reads « Peu utilisés ».
 */

export type UsagePreset = 'low' | 'mid' | 'high' | 'custom';

/** The two bounds of a usage filter, in hours; null = no bound on that side. */
export interface UsageBounds {
  below: number | null;
  above: number | null;
}

/** The console's two thresholds, as the list response serves them. */
export interface UsageThresholds {
  low: number;
  high: number;
}

/** The bounds a preset stands for. `custom` has none of its own. */
export function usagePresetBounds(
  preset: Exclude<UsagePreset, 'custom'>,
  thresholds: UsageThresholds,
): UsageBounds {
  switch (preset) {
    case 'low':
      return { below: thresholds.low, above: null };
    case 'mid':
      return { below: thresholds.high, above: thresholds.low };
    case 'high':
      return { below: null, above: thresholds.high };
  }
}

/**
 * Which preset a pair of bounds is, if any: null when there is no bound at
 * all, `custom` when there are bounds no preset matches — or no thresholds
 * yet to match them against.
 */
export function usagePresetOf(
  bounds: UsageBounds,
  thresholds: UsageThresholds | null,
): UsagePreset | null {
  if (bounds.below === null && bounds.above === null) return null;
  if (thresholds) {
    for (const preset of ['low', 'mid', 'high'] as const) {
      const p = usagePresetBounds(preset, thresholds);
      if (p.below === bounds.below && p.above === bounds.above) return preset;
    }
  }
  return 'custom';
}

/** Hours as the console writes them: « 12,4 h », « 0 h ». */
export function hoursLabel(hours: number): string {
  return t('machines.usage.hours', {
    hours: hours.toLocaleString(intlTag(), { maximumFractionDigits: 1 }),
  });
}

/** The chip under the search bar, in words: what the list is narrowed to. */
export function usageFilterLabel(bounds: UsageBounds, days: number | null): string {
  const { below, above } = bounds;
  // The window named when there is one: « … sur 7 j ».
  const over = days ? 'Over' : '';
  if (below !== null && above !== null) {
    return t(`machines.usage.between${over}`, {
      above: hoursLabel(above),
      below: hoursLabel(below),
      days,
    });
  }
  if (below !== null) return t(`machines.usage.below${over}`, { below: hoursLabel(below), days });
  if (above !== null) return t(`machines.usage.above${over}`, { above: hoursLabel(above), days });
  return t('machines.usage.none');
}

/**
 * A figure typed in a bound's box, as hours: a non-negative number, or null.
 * QInput hands back what was typed, whatever its `type`, and the URL a parsed
 * number; this is the one reading both go through.
 */
export function parseHours(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(typeof value === 'string' ? value.replace(',', '.') : value);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

/**
 * Why a set of usage settings would be refused, in the words the form shows —
 * or null when it holds together. The server checks the same rules; checking
 * them here too names the field before a round trip does.
 */
export function usageSettingsError(
  windowDays: unknown,
  lowHours: unknown,
  highHours: unknown,
): string | null {
  const whole = (v: unknown) => typeof v === 'number' && Number.isInteger(v);
  if (!whole(windowDays) || (windowDays as number) < 1 || (windowDays as number) > 90) {
    return t('machines.usage.settings.window');
  }
  if (!whole(lowHours) || (lowHours as number) < 0) {
    return t('machines.usage.settings.low');
  }
  if (!whole(highHours) || (highHours as number) < 1) {
    return t('machines.usage.settings.high');
  }
  if ((lowHours as number) >= (highHours as number)) {
    return t('machines.usage.settings.order');
  }
  const hours = 24 * (windowDays as number);
  if ((highHours as number) > hours) {
    return t('machines.usage.settings.highOverWindow', { hours });
  }
  return null;
}
