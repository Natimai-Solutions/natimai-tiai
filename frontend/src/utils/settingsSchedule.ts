/**
 * The page Paramètres' mail schedule and agent version field, as pure functions.
 *
 * The server keeps the digest hour in UTC — one parc, one clock, whatever the
 * zone of the administrator who set it — but nobody thinks of their morning
 * mail in UTC. These functions say when it lands for the reader: 18 h UTC is
 * 08:00 in Tahiti, and a reminder sent on Monday at 02:00 UTC reaches Tahiti on
 * Sunday afternoon, which is the kind of surprise the page must state, not
 * leave to be discovered.
 */

/** 0 = Monday … 6 = Sunday, as the server numbers them. */
export const WEEKDAYS_FR = [
  'lundi',
  'mardi',
  'mercredi',
  'jeudi',
  'vendredi',
  'samedi',
  'dimanche',
] as const;

/** The reader's own zone, as the browser knows it. */
export function readerTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
}

/**
 * The instant `hour`:00 UTC falls on, on the first day at or after `ref`
 * that is `weekday` in UTC (any day when `weekday` is null). Built on `ref`'s
 * date so daylight saving time is the one in force around it.
 */
function utcInstant(hour: number, weekday: number | null, ref: Date): Date {
  const base = new Date(Date.UTC(ref.getUTCFullYear(), ref.getUTCMonth(), ref.getUTCDate(), hour));
  if (weekday === null) return base;
  // JS numbers Sunday 0; the server numbers Monday 0.
  const current = (base.getUTCDay() + 6) % 7;
  const ahead = (weekday - current + 7) % 7;
  return new Date(base.getTime() + ahead * 24 * 3600 * 1000);
}

function localParts(instant: Date, timeZone: string): { weekday: string; time: string } {
  const fmt = new Intl.DateTimeFormat('fr-FR', {
    timeZone,
    weekday: 'long',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  });
  const parts = fmt.formatToParts(instant);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  return { weekday: get('weekday'), time: `${get('hour')}:${get('minute')}` };
}

/** « 08:00 » — when `hour`:00 UTC reads on the reader's clock. */
export function localTimeOfUtcHour(hour: number, timeZone: string, ref: Date = new Date()): string {
  return localParts(utcInstant(hour, null, ref), timeZone).time;
}

/**
 * The digest as the reader will receive it: « chaque jour à 08:00 ». Daily,
 * so a local date that differs from the UTC one changes nothing here — it
 * does for the weekly reminder below.
 */
export function digestSummary(hour: number, timeZone: string, ref: Date = new Date()): string {
  const instant = utcInstant(hour, null, ref);
  const { time } = localParts(instant, timeZone);
  return `chaque jour à ${time} (${timeZone})`;
}

/**
 * The weekly reminder as the reader will receive it: « le lundi à 08:00 » —
 * on the *local* weekday, which is not always the one chosen in UTC.
 */
export function reminderSummary(
  weekday: number,
  hour: number,
  timeZone: string,
  ref: Date = new Date(),
): string {
  const { weekday: localDay, time } = localParts(utcInstant(hour, weekday, ref), timeZone);
  return `le ${localDay} à ${time} (${timeZone})`;
}

// An agent version as the release workflow stamps it ("1.0.2", "v1.0.2",
// "1.1.0-rc.1"), or empty for « automatique » — the server's own rule.
const AGENT_VERSION = /^(|v?\d+(\.\d+){0,3}([-+][0-9A-Za-z.-]+)?)$/;

/** Whether the server will accept this as the reference agent version. */
export function isAgentVersion(value: string): boolean {
  return AGENT_VERSION.test(value.trim());
}
