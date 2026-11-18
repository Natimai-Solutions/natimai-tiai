import { defineBoot } from '#q-app';
import { Lang } from 'quasar';
import langEn from 'quasar/lang/en-GB';
import langFr from 'quasar/lang/fr';
import { watch } from 'vue';
import { availableLocales, i18n, onLocaleChange, resolveLocale, setLocale } from 'src/i18n';
import { browserLanguages } from 'src/i18n/locales';
import { useAuthStore } from 'src/stores/auth';

/**
 * Install the translations and keep the language in step with the account:
 * its choice once its profile is read, else the browser's (plan
 * `dev/plan-console-bilingue.md`, §4.1). Runs after the `pinia` boot file.
 *
 * Quasar's own pack (table pagination, date pickers) follows on every change.
 */
export default defineBoot(({ app }) => {
  app.use(i18n);
  onLocaleChange((locale) =>
    // Quasar's pack type and `Lang.set`'s parameter disagree on `formatNumber`
    // under `exactOptionalPropertyTypes`: the pack is the one Quasar ships.
    Lang.set((locale === 'en' ? langEn : langFr) as Parameters<typeof Lang.set>[0]),
  );

  const auth = useAuthStore();
  watch(
    () => auth.user?.language ?? null,
    (chosen) => setLocale(resolveLocale(chosen, browserLanguages(), availableLocales())),
    { immediate: true },
  );
});
