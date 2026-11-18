/**
 * The console's languages, and which one a reader gets (plan
 * `dev/plan-console-bilingue.md`, §4.1).
 *
 * Kept apart from `src/i18n/index.ts` so that this logic — pure, no Vue — is
 * tested on its own.
 */

export const LOCALES = ['fr', 'en'] as const;
export type Locale = (typeof LOCALES)[number];

/** The language of an installation that says nothing, and of a missing text. */
export const DEFAULT_LOCALE: Locale = 'fr';

/**
 * Whether English is offered. It was false until every text of the console
 * was in the catalogues (plan, jalon I6): an English reader would have got a
 * page half in French. A further language starts the same way — in
 * `LOCALES`, offered only once complete.
 */
export const ENGLISH_AVAILABLE = true;

export function availableLocales(): Locale[] {
  return ENGLISH_AVAILABLE ? [...LOCALES] : [DEFAULT_LOCALE];
}

/** The BCP 47 tag dates and numbers are written with. `en-GB` and not `en-US`:
 *  the day before the month, as the French reader of the same parc writes it. */
export const INTL_TAGS: Record<Locale, string> = { fr: 'fr-FR', en: 'en-GB' };

function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (LOCALES as readonly string[]).includes(value);
}

/** The browser's preferred languages, most wanted first; none outside a browser. */
export function browserLanguages(): readonly string[] {
  if (typeof navigator === 'undefined') return [];
  if (navigator.languages?.length) return navigator.languages;
  return navigator.language ? [navigator.language] : [];
}

/**
 * The language to show: the account's choice when it made one the console
 * offers, else the first of the browser's languages the console offers
 * (`en-US` reads as `en`), else French.
 */
export function resolveLocale(
  chosen: string | null | undefined,
  browser: readonly string[] = browserLanguages(),
  available: readonly Locale[] = availableLocales(),
): Locale {
  if (isLocale(chosen) && available.includes(chosen)) return chosen;
  for (const tag of browser) {
    const primary = tag.toLowerCase().split('-')[0];
    if (isLocale(primary) && available.includes(primary)) return primary;
  }
  return DEFAULT_LOCALE;
}
