import type { MachineUsage } from 'src/services/machines';

/**
 * The fiche's usage histogram, as data: one bar per calendar day.
 *
 * Kept out of the component so the one rule that matters is tested: a day
 * before the server started counting — before this poste was enrolled, or
 * before the feature was deployed at all — is not a day at zero hours. It is
 * a day nobody measured, and the chart says so instead of drawing it as idle.
 */

/** A day holds 24 hours: the chart's fixed scale, so two postes compare. */
export const HOURS_PER_DAY = 24;

export interface UsageBar {
  /** `YYYY-MM-DD`, a local calendar day. */
  date: string;
  hours: number;
  /** Height as a percentage of a full day, 0–100. */
  percent: number;
  /** False for a day before counting began: drawn empty, read « non mesuré ». */
  counted: boolean;
  /** « lun. 29/09 », for the tooltip and the table. */
  label: string;
  /** Saturday or Sunday: shaded, since a school parc is expected off then. */
  weekend: boolean;
}

/**
 * `YYYY-MM-DD` of an instant in `tz` — the zone the server cut the days in,
 * which it reports back (`MachineUsage.tz`). Not the browser's own: the two
 * agree in practice, but the server falls back to UTC on a zone name it does
 * not know, and the boundary day would then be filed on the wrong side.
 */
export function localDate(iso: string, tz: string): string {
  // en-CA writes dates as YYYY-MM-DD, the one locale that does.
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: tz,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(iso));
}

/** The first local day that was measured: the later of enrolment and the parc's first count. */
export function countedFrom(
  usage: Pick<MachineUsage, 'first_seen' | 'usage_since' | 'tz'>,
): string | null {
  if (!usage.usage_since) return null;
  const a = localDate(usage.first_seen, usage.tz);
  const b = localDate(usage.usage_since, usage.tz);
  return a > b ? a : b;
}

function dayOf(date: string): Date {
  const [y, m, d] = date.split('-').map(Number);
  return new Date(y!, m! - 1, d!);
}

export function usageBars(usage: MachineUsage): UsageBar[] {
  const from = countedFrom(usage);
  return usage.daily.map(({ date, hours }) => {
    const day = dayOf(date);
    const weekday = day.getDay();
    return {
      date,
      hours,
      percent: Math.min(100, Math.max(0, (hours / HOURS_PER_DAY) * 100)),
      counted: from !== null && date >= from,
      label: day.toLocaleDateString('fr-FR', {
        weekday: 'short',
        day: '2-digit',
        month: '2-digit',
      }),
      weekend: weekday === 0 || weekday === 6,
    };
  });
}

/** How many of the days were measured — the divisor of a daily average. */
export function measuredDays(bars: UsageBar[]): number {
  return bars.filter((b) => b.counted).length;
}
