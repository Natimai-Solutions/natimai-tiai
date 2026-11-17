// Lives with the page specs for their DOM (`components` project): the layout
// is the frame every page is shown in.
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/auth')>()),
  getMe: vi.fn(),
}));
vi.mock('src/services/checks', () => ({
  listChecks: vi.fn(() => Promise.resolve({ items: [], total: 0 })),
}));
vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  getDue: vi.fn(() => Promise.resolve(null)),
}));

import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { getMe, type User } from 'src/services/auth';
import { setAccessToken } from 'src/services/session';
import { PROFILE_REFRESH_MS, useAuthStore } from 'src/stores/auth';
import MainLayout from 'src/layouts/MainLayout.vue';

const Stub = defineComponent({ render: () => h('div') });
const slot = { template: '<div><slot /></div>' };

function profile(permissions: string[]): User {
  return {
    id: 'me',
    email: 'me@x',
    full_name: null,
    email_preference: 'none',
    preferences: {},
    groups: [],
    permissions,
  };
}

async function mountLayout(user: User | null, path = '/machines') {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = user;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/',
        name: 'dashboard',
        component: Stub,
        meta: { requiresPermission: 'machine:read' },
      },
      {
        path: '/machines',
        name: 'machines',
        component: Stub,
        meta: { requiresPermission: 'machine:read' },
      },
      { path: '/software', name: 'software', component: Stub },
      { path: '/rooms', name: 'rooms', component: Stub, meta: { requiresPermission: 'room:read' } },
      { path: '/account', name: 'account', component: Stub },
      { path: '/no-access', name: 'no-access', component: Stub },
      { path: '/:other(.*)*', component: Stub },
    ],
  });
  await router.push(path);
  const w = mount(MainLayout, {
    attachTo: document.body,
    global: {
      plugins: [pinia, router],
      stubs: { QLayout: slot, QHeader: slot, QDrawer: slot, QPageContainer: slot },
    },
  });
  await flushPromises();
  return { w, router };
}

const menu = (w: Awaited<ReturnType<typeof mountLayout>>['w']) =>
  w.findAll('.q-item').map((i) => i.text());

describe('MainLayout', () => {
  beforeEach(() => {
    vi.mocked(getMe).mockReset();
    setAccessToken('token');
  });
  afterEach(() => {
    vi.useRealTimers();
    setAccessToken(null);
    document.body.innerHTML = '';
  });

  // Item 4: the menu offers what the account can read.
  it('hides the parc pages from an account without machine:read', async () => {
    const { w } = await mountLayout(profile(['room:read']), '/rooms');
    const entries = menu(w).join(' | ');
    expect(entries).not.toContain('Tableau de bord');
    expect(entries).not.toContain('Postes');
    expect(entries).toContain('Salles');
  });

  // Item 4: rights withdrawn during the session.
  it('leaves a page whose right was withdrawn, for the first one still readable', async () => {
    const { router } = await mountLayout(profile(['machine:read', 'room:read']), '/machines');
    useAuthStore().user = profile(['room:read']);
    await flushPromises();
    expect(router.currentRoute.value.name).toBe('rooms');
  });

  it('reads the profile again every few minutes', async () => {
    vi.useFakeTimers();
    vi.mocked(getMe).mockResolvedValue(profile(['machine:read', 'audit:read']));
    const { w } = await mountLayout(profile(['machine:read']));
    vi.advanceTimersByTime(PROFILE_REFRESH_MS);
    await flushPromises();
    expect(getMe).toHaveBeenCalledTimes(1);
    expect(menu(w).join(' | ')).toContain("Journal d'audit");
  });

  // Item 2: the profile could not be read at load.
  it('says the profile could not be read, and reads it again on « Réessayer »', async () => {
    vi.mocked(getMe).mockRejectedValueOnce({ response: { status: 500, data: {} } });
    const { w } = await mountLayout(null);
    expect(w.findComponent(LoadErrorBanner).exists()).toBe(true);

    vi.mocked(getMe).mockResolvedValueOnce(profile(['machine:read']));
    w.findComponent(LoadErrorBanner).vm.$emit('retry');
    await flushPromises();
    expect(w.findComponent(LoadErrorBanner).exists()).toBe(false);
    expect(menu(w).join(' | ')).toContain('Postes');
  });

  // Item 12.
  it('offers « Aller au contenu » first, and moves the focus into the page', async () => {
    const { w } = await mountLayout(profile(['machine:read']));
    const link = w.find('a.skip-link');
    expect(link.text()).toBe('Aller au contenu');
    await link.trigger('click');
    expect(document.activeElement?.id).toBe('main-content');
  });
});
