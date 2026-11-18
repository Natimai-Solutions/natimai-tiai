/**
 * The console's translations (plan `dev/plan-console-bilingue.md`, §4.1).
 *
 * One vue-i18n instance, in composition mode, whose `t` is importable from
 * anywhere — a page, a utility, a service, a test — without mounting a
 * plugin: `import { t } from 'src/i18n'`. Templates re-render when the
 * language changes, the locale being a ref.
 *
 * vue-i18n 11 compiles messages without `eval` (its JIT compiler), which the
 * Content-Security-Policy of the deployment (`script-src 'self'`) requires.
 */
import { createI18n } from 'vue-i18n';
import errorCodes from './messages/errorCodes';
import { en, fr, type MessageSchema } from './messages';
import { DEFAULT_LOCALE, INTL_TAGS, type Locale } from './locales';

export { availableLocales, resolveLocale, ENGLISH_AVAILABLE, LOCALES } from './locales';
export type { Locale } from './locales';

export const i18n = createI18n<[MessageSchema], Locale, false>({
  legacy: false,
  locale: DEFAULT_LOCALE,
  fallbackLocale: DEFAULT_LOCALE,
  messages: { fr, en },
  // A missing key falls back to French, silently: the reader gets a text.
  missingWarn: false,
  fallbackWarn: false,
});

const composer = i18n.global;

/** Translate a key of the catalogues. */
export const t = composer.t;

/** The language shown now. */
export function currentLocale(): Locale {
  return composer.locale.value;
}

/** The BCP 47 tag to format dates and numbers with, for the language shown. */
export function intlTag(): string {
  return INTL_TAGS[currentLocale()];
}

/** An API error code's message in the language shown, or null for an unknown code. */
export function errorCodeMessage(code: string): string | null {
  const table: Record<string, string> = errorCodes[currentLocale()];
  return Object.prototype.hasOwnProperty.call(table, code) ? (table[code] ?? null) : null;
}

type LocaleListener = (locale: Locale) => void;
const listeners = new Set<LocaleListener>();

/** Called on every change of language — the Quasar pack follows this way. */
export function onLocaleChange(listener: LocaleListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Show the console in `locale`: texts, the page's `lang`, and the listeners. */
export function setLocale(locale: Locale): void {
  if (composer.locale.value !== locale) composer.locale.value = locale;
  if (typeof document !== 'undefined') document.documentElement.lang = locale;
  for (const listener of listeners) listener(locale);
}
