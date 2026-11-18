// Lives with the page specs for their DOM (`components` project): the layout
// is the frame every page is shown in.
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QPage } from 'quasar';
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
import { listChecks } from 'src/services/checks';
import { notifyTasksChanged } from 'src/composables/useTasksBadge';
import { getDue } from 'src/services/maintenance';
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

// A page as every page of the console is: a `q-page`, which renders `<main>`.
const PageStub = defineComponent({ render: () => h(QPage, null, () => 'page') });

async function mountLayout(user: User | null, path = '/machines', realLayout = false) {
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
      { path: '/page', name: 'page', component: PageStub },
      { path: '/tasks', name: 'tasks', component: Stub },
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
      stubs: realLayout
        ? {}
        : { QLayout: slot, QHeader: slot, QDrawer: slot, QPageContainer: slot },
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
    vi.unstubAllGlobals();
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

  // Review finding 2: a tab nobody looks at must not keep its session alive.
  // `/auth/me` every five minutes renews the access token as it expires, and
  // each renewal pushes the idle expiry of the session back.
  describe('in a hidden tab', () => {
    function setHidden(hidden: boolean) {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
      document.dispatchEvent(new Event('visibilitychange'));
    }
    afterEach(() => {
      // Back to jsdom's own (visible) document.
      delete (document as unknown as { hidden?: boolean }).hidden;
    });

    it('sends nothing, then reads the profile once when the tab is shown again', async () => {
      vi.useFakeTimers();
      vi.mocked(getMe).mockResolvedValue(profile(['machine:read', 'check:read']));
      await mountLayout(profile(['machine:read', 'check:read']));
      vi.mocked(listChecks).mockClear();

      setHidden(true);
      vi.advanceTimersByTime(PROFILE_REFRESH_MS * 12);
      await flushPromises();
      expect(getMe).not.toHaveBeenCalled();
      expect(listChecks).not.toHaveBeenCalled();

      // Back in front of the reader: one read for the hour missed, not twelve.
      setHidden(false);
      await flushPromises();
      expect(getMe).toHaveBeenCalledTimes(1);
    });

    it('reads nothing on a return that missed no tick', async () => {
      vi.useFakeTimers();
      vi.mocked(getMe).mockResolvedValue(profile(['machine:read']));
      await mountLayout(profile(['machine:read']));
      setHidden(true);
      vi.advanceTimersByTime(PROFILE_REFRESH_MS / 2);
      setHidden(false);
      await flushPromises();
      expect(getMe).not.toHaveBeenCalled();
      // And the pace is kept: the next read is the timer's.
      vi.advanceTimersByTime(PROFILE_REFRESH_MS / 2);
      await flushPromises();
      expect(getMe).toHaveBeenCalledTimes(1);
    });

    it('stops with the layout', async () => {
      vi.useFakeTimers();
      vi.mocked(getMe).mockResolvedValue(profile(['machine:read']));
      const { w } = await mountLayout(profile(['machine:read']));
      setHidden(true);
      vi.advanceTimersByTime(PROFILE_REFRESH_MS);
      w.unmount();
      setHidden(false);
      vi.advanceTimersByTime(PROFILE_REFRESH_MS);
      await flushPromises();
      expect(getMe).not.toHaveBeenCalled();
    });
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

  // Review finding 9: on a 5xx the banner read « Erreur interne du serveur »
  // alone, over an empty menu — what is wrong is the profile, whatever the
  // server said about it.
  it('names the profile in the banner whatever the failure, the server’s words after', async () => {
    vi.mocked(getMe).mockRejectedValueOnce({
      response: { status: 500, data: { error: { code: 'internal.server_error' } } },
    });
    const { w } = await mountLayout(null);
    const text = w.findComponent(LoadErrorBanner).text();
    expect(text).toContain('Impossible de charger votre profil');
    expect(text).toContain('les menus et les actions sont incomplets');
    expect(text).toContain('Erreur interne du serveur');

    // The network down: no answer to quote, the same sentence alone.
    vi.mocked(getMe).mockRejectedValueOnce(new Error('Network Error'));
    w.findComponent(LoadErrorBanner).vm.$emit('retry');
    await flushPromises();
    const offline = w.findComponent(LoadErrorBanner).text();
    expect(offline).toContain('Impossible de charger votre profil');
    expect(offline).not.toContain('Erreur interne');
    expect(offline).not.toContain('Network Error');
  });

  // Review finding 8: « Mes tâches » is offered to an account that only
  // follows maintenance; its overdue count is asked under that right alone.
  describe('the badges of « Mes tâches »', () => {
    const tasksEntry = (w: Awaited<ReturnType<typeof mountLayout>>['w']) =>
      w.findAll('.q-item').find((i) => i.text().includes('Mes tâches'))!;

    beforeEach(() => {
      vi.mocked(listChecks).mockClear();
      vi.mocked(getDue).mockClear();
    });
    afterEach(() => {
      vi.mocked(listChecks).mockImplementation(() =>
        Promise.resolve({ items: [], total: 0 } as never),
      );
      vi.mocked(getDue).mockImplementation(() => Promise.resolve(null as never));
    });

    it('counts the overdue postes of a maintenance-only account', async () => {
      vi.mocked(getDue).mockResolvedValue({ overdue: 3 } as never);
      const { w } = await mountLayout(profile(['maintenance:read']), '/account');
      expect(getDue).toHaveBeenCalledWith('me');
      // Not its right: asking would be a 403 on every page.
      expect(listChecks).not.toHaveBeenCalled();
      expect(
        tasksEntry(w)
          .findAll('.q-badge')
          .map((b) => b.text()),
      ).toEqual(['3']);
    });

    it('counts the checks of an account without the maintenance right', async () => {
      vi.mocked(listChecks).mockResolvedValue({ items: [], total: 2 } as never);
      const { w } = await mountLayout(profile(['check:read']), '/account');
      expect(listChecks).toHaveBeenCalledTimes(1);
      expect(getDue).not.toHaveBeenCalled();
      expect(
        tasksEntry(w)
          .findAll('.q-badge')
          .map((b) => b.text()),
      ).toEqual(['2']);
    });

    it('shows both, and one count failing does not hide the other', async () => {
      vi.mocked(listChecks).mockRejectedValue(new Error('500'));
      vi.mocked(getDue).mockResolvedValue({ overdue: 4 } as never);
      const { w } = await mountLayout(profile(['check:read', 'maintenance:read']), '/account');
      expect(
        tasksEntry(w)
          .findAll('.q-badge')
          .map((b) => b.text()),
      ).toEqual(['4']);
    });

    // A right withdrawn during the session takes its count with it, at the
    // next count (the entry stays: the other right still offers it).
    it('drops the count of a right withdrawn during the session', async () => {
      vi.mocked(listChecks).mockResolvedValue({ items: [], total: 2 } as never);
      vi.mocked(getDue).mockResolvedValue({ overdue: 5 } as never);
      const { w } = await mountLayout(profile(['check:read', 'maintenance:read']), '/account');
      const badges = () =>
        tasksEntry(w)
          .findAll('.q-badge')
          .map((b) => b.text());
      expect(badges()).toEqual(['2', '5']);
      const auth = useAuthStore();

      auth.user = profile(['maintenance:read']);
      notifyTasksChanged();
      await flushPromises();
      expect(badges()).toEqual(['5']);

      auth.user = profile(['check:read']);
      notifyTasksChanged();
      await flushPromises();
      expect(badges()).toEqual(['2']);
    });

    it('asks nothing for an account with neither right', async () => {
      await mountLayout(profile(['machine:read']));
      expect(listChecks).not.toHaveBeenCalled();
      expect(getDue).not.toHaveBeenCalled();
    });
  });

  // Item 12.
  it('offers « Aller au contenu » first, and moves the focus into the page', async () => {
    const { w } = await mountLayout(profile(['machine:read']));
    const link = w.find('a.skip-link');
    expect(link.text()).toBe('Aller au contenu');
    expect(link.attributes('href')).toBe('#main-content');
    await link.trigger('click');
    expect(document.activeElement?.id).toBe('main-content');
  });

  // Review finding 7: every page is a `q-page`, which is the `<main>`
  // landmark; a second one around it nests two.
  it('has one main landmark, the page’s, inside the target of the skip link', async () => {
    // The real layout this once — it measures itself, which jsdom cannot.
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    const { w } = await mountLayout(profile(['machine:read']), '/page', true);
    const mains = w.findAll('main');
    expect(mains).toHaveLength(1);
    expect(mains[0]!.classes()).toContain('q-page');
    expect(w.find('#main-content').element.contains(mains[0]!.element)).toBe(true);
    await w.find('a.skip-link').trigger('click');
    expect(document.activeElement?.id).toBe('main-content');
  });
});
