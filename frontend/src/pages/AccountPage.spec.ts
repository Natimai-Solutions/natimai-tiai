import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/auth')>()),
  listSessions: vi.fn(),
}));

import { listSessions } from 'src/services/auth';
import { useAuthStore } from 'src/stores/auth';
import AccountPage from './AccountPage.vue';

async function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'me',
    email: 'a@b.c',
    permissions: [],
    groups: [],
    email_preference: 'none',
    preferences: {},
  } as never;
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

describe('AccountPage — open sessions (item 2)', () => {
  beforeEach(() => vi.mocked(listSessions).mockReset());

  it('never says « Aucune session ouverte » when the list could not be read', async () => {
    vi.mocked(listSessions).mockRejectedValueOnce({ response: { status: 500, data: {} } });
    const w = await mountPage();
    expect(w.text()).not.toContain('Aucune session ouverte');
    expect(w.text()).toContain('Impossible de charger vos sessions ouvertes');

    vi.mocked(listSessions).mockResolvedValueOnce([]);
    await w
      .findAll('button')
      .find((b) => b.text().includes('Réessayer'))!
      .trigger('click');
    await flushPromises();
    expect(w.text()).toContain('Aucune session ouverte');
  });
});
