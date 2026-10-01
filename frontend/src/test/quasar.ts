import { config } from '@vue/test-utils';
import { Dialog, Notify, Quasar } from 'quasar';
import langFr from 'quasar/lang/fr.js';
import { afterAll, beforeAll } from 'vitest';

/**
 * Quasar as the app installs it (see `framework` in quasar.config.ts): the
 * same plugins, the same language pack — so a test reads the labels a user
 * reads, « Lignes par page » and not « Records per page ».
 *
 * The components themselves need no registration: the Quasar Vite plugin in
 * vitest.config.ts resolves `<q-btn>` and friends at compile time, as in the
 * app build. What a mount lacks without this is the `$q` the components inject
 * (screen size, language, dark mode) and the plugins behind `$q.notify`.
 */
export const quasarTestOptions = { plugins: { Dialog, Notify }, lang: langFr };

/**
 * jsdom has no `screen.orientation`, which Quasar's Screen plugin reads as it
 * installs — every mount would throw on it. A landscape desktop screen that
 * never turns is all a component test needs.
 */
function stubScreenOrientation(): void {
  if (window.screen.orientation) return;
  Object.defineProperty(window.screen, 'orientation', {
    configurable: true,
    value: {
      type: 'landscape-primary',
      angle: 0,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    },
  });
}

/**
 * Install Quasar into every `mount` of the current spec file. Called by the
 * components project's setup file; a composable spec that mounts a host
 * component calls it itself. A home-made helper rather than the
 * `@quasar/quasar-app-extension-testing-unit-vitest` app extension: this is
 * all of what its helper does, and the extension would also rewrite the
 * Quasar config and pin its own Vitest range.
 */
export function installQuasarPlugin(): void {
  const entry = [Quasar, quasarTestOptions] as const;
  beforeAll(() => {
    stubScreenOrientation();
    config.global.plugins.unshift(entry as unknown as (typeof config.global.plugins)[number]);
  });
  afterAll(() => {
    const i = config.global.plugins.indexOf(
      entry as unknown as (typeof config.global.plugins)[number],
    );
    if (i >= 0) config.global.plugins.splice(i, 1);
  });
}
