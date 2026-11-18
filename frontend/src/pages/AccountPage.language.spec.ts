import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createMemoryHistory, createRouter } from 'vue-router';

// English offered, as it will be once the console is translated (plan I6).
const offered = vi.hoisted(() => ({ english: true }));
vi.mock('src/i18n/locales', async (importOriginal) => {
  const actual = await importOriginal<typeof import('src/i18n/locales')>();
  return {
    ...actual,
    availableLocales: () => (offered.english ? ['fr', 'en'] : ['fr']),
  };
});
vi.mock('src/services/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/auth')>()),
  listSessions: vi.fn().mockResolvedValue([]),
  updateMe: vi.fn(),
}));

import { updateMe, type User } from 'src/services/auth';
import { setLocale } from 'src/i18n';
import { useAuthStore } from 'src/stores/auth';
import AccountPage from './AccountPage.vue';

const me = {
  id: 'me',
  email: 'a@b.c',
  permissions: [],
  groups: [],
  email_preference: 'none',
  language: null,
  preferences: {},
} as unknown as User;

async function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = { ...me };
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { render: () => null } }],
  });
  const w = mount(AccountPage, {
    global: { plugins: [pinia, router], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  return w;
}

afterEach(() => {
  offered.english = true;
  setLocale('fr');
});

describe('AccountPage — language (plan console bilingue, I1)', () => {
  it('offers nothing to choose while the console speaks French only', async () => {
    offered.english = false;
    const w = await mountPage();
    expect(w.find('[data-test="language-card"]').exists()).toBe(false);
  });

  it('saves the account’s language, and « the browser’s » as no choice', async () => {
    const w = await mountPage();
    const card = w.find('[data-test="language-card"]');
    expect(card.text()).toContain('Celle du navigateur');
    expect(card.text()).toContain('English');

    vi.mocked(updateMe).mockResolvedValueOnce({ ...me, language: 'en' });
    const radios = card.findAll('[role="radio"]');
    await radios[2]!.trigger('click');
    await flushPromises();
    expect(updateMe).toHaveBeenCalledWith({ language: 'en' });
    expect(useAuthStore().user?.language).toBe('en');

    vi.mocked(updateMe).mockResolvedValueOnce({ ...me, language: null });
    await radios[0]!.trigger('click');
    await flushPromises();
    expect(updateMe).toHaveBeenLastCalledWith({ language: null });
    expect(useAuthStore().user?.language).toBeNull();
  });
});
