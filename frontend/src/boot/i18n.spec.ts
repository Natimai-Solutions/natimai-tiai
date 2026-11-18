import { createPinia, setActivePinia } from 'pinia';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';

const offered = vi.hoisted(() => ({ english: true }));
vi.mock('src/i18n/locales', async (importOriginal) => {
  const actual = await importOriginal<typeof import('src/i18n/locales')>();
  return {
    ...actual,
    availableLocales: () => (offered.english ? ['fr', 'en'] : ['fr']),
    browserLanguages: () => ['fr-FR'],
  };
});
const langSet = vi.hoisted(() => vi.fn());
vi.mock('quasar', () => ({ Lang: { set: langSet } }));

import { currentLocale, setLocale } from 'src/i18n';
import { useAuthStore } from 'src/stores/auth';
import boot from './i18n';

afterEach(() => {
  offered.english = true;
  setLocale('fr');
});

async function start() {
  setActivePinia(createPinia());
  const app = { use: vi.fn() };
  await (boot as unknown as (ctx: { app: typeof app }) => unknown)({ app });
  return app;
}

describe('boot/i18n', () => {
  it('installs vue-i18n and follows the account’s language once read', async () => {
    const app = await start();
    expect(app.use).toHaveBeenCalledTimes(1);
    expect(currentLocale()).toBe('fr');

    useAuthStore().user = { language: 'en' } as never;
    await nextTick();
    expect(currentLocale()).toBe('en');
    expect(langSet).toHaveBeenLastCalledWith(expect.objectContaining({ isoName: 'en-GB' }));

    // Logged out: back to the browser's, French here.
    useAuthStore().user = null;
    await nextTick();
    expect(currentLocale()).toBe('fr');
    expect(langSet).toHaveBeenLastCalledWith(expect.objectContaining({ isoName: 'fr' }));
  });

  it('keeps an updated installation in French while English is not offered', async () => {
    offered.english = false;
    await start();
    useAuthStore().user = { language: 'en' } as never;
    await nextTick();
    expect(currentLocale()).toBe('fr');
  });
});
