import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/auth')>()),
  getMe: vi.fn(),
  getAuthMethods: vi.fn(),
  startDirectoryLink: vi.fn(),
  unlinkDirectory: vi.fn(),
}));

import {
  getAuthMethods,
  getMe,
  startDirectoryLink,
  unlinkDirectory,
  type User,
} from 'src/services/auth';
import { setAccessToken } from 'src/services/session';
import { useAuthStore } from 'src/stores/auth';
import DirectoryCard from './DirectoryCard.vue';

const Stub = defineComponent({ render: () => h('div') });

function me(fields: Partial<User> = {}): User {
  return {
    id: 'u',
    email: 'a@b.c',
    full_name: null,
    email_preference: 'digest_daily',
    preferences: {},
    groups: [],
    permissions: [],
    auth_source: 'local',
    directory_linked: false,
    ...fields,
  };
}

async function mountCard(user: User) {
  const pinia = createPinia();
  setActivePinia(pinia);
  setAccessToken('t');
  useAuthStore().user = user;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/account', component: Stub }],
  });
  await router.push('/account');
  const w = mount(DirectoryCard, { global: { plugins: [pinia, router] } });
  await flushPromises();
  return w;
}

describe('DirectoryCard', () => {
  beforeEach(() => {
    vi.mocked(getAuthMethods)
      .mockReset()
      .mockResolvedValue({ oidc_enabled: true, oidc_label: 'Microsoft' });
    vi.mocked(startDirectoryLink).mockReset();
    vi.mocked(unlinkDirectory).mockReset();
    vi.mocked(getMe).mockReset();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('links a local account by sending the browser to the provider', async () => {
    vi.mocked(startDirectoryLink).mockResolvedValue('https://login.test/authorize?x=1');
    const assign = vi.fn();
    vi.stubGlobal('location', { ...window.location, assign });
    const w = await mountCard(me());
    expect(w.text()).toContain('Compte Microsoft');
    expect(w.text()).toContain('Non associé');
    await w.find('[data-test="directory-link"]').trigger('click');
    await flushPromises();
    expect(assign).toHaveBeenCalledWith('https://login.test/authorize?x=1');
  });

  it('unlinks a linked account', async () => {
    vi.mocked(unlinkDirectory).mockResolvedValue();
    vi.mocked(getMe).mockResolvedValue(me());
    const w = await mountCard(me({ directory_linked: true }));
    expect(w.text()).toContain('Associé');
    await w.find('[data-test="directory-unlink"]').trigger('click');
    await flushPromises();
    expect(unlinkDirectory).toHaveBeenCalled();
    expect(w.find('[data-test="directory-link"]').exists()).toBe(true);
  });

  it('is absent without the directory, and for an account of the directory', async () => {
    vi.mocked(getAuthMethods).mockResolvedValue({ oidc_enabled: false, oidc_label: 'Microsoft' });
    let w = await mountCard(me());
    expect(w.find('[data-test="directory-card"]').exists()).toBe(false);
    vi.mocked(getAuthMethods).mockResolvedValue({ oidc_enabled: true, oidc_label: 'Microsoft' });
    w = await mountCard(me({ auth_source: 'oidc' }));
    expect(w.find('[data-test="directory-card"]').exists()).toBe(false);
  });
});
