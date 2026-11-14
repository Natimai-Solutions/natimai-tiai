import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/stats', () => ({ getOverview: vi.fn() }));
vi.mock('src/services/machines', () => ({ listMachines: vi.fn() }));
vi.mock('src/services/threats', () => ({ listThreats: vi.fn() }));

import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { listMachines } from 'src/services/machines';
import { getOverview, type StatsOverview } from 'src/services/stats';
import { listThreats } from 'src/services/threats';
import { useAuthStore } from 'src/stores/auth';
import DashboardPage from './DashboardPage.vue';

const Stub = defineComponent({ render: () => h('div') });

const overview = {
  total: 3,
  software_count: 10,
  usage_since: null,
  usage_window_days: 30,
  usage_low_hours: 10,
  usage_high_hours: 200,
} as unknown as StatsOverview;

const empty = { items: [], total: 0, page: 1, page_size: 5 };
const fail500 = {
  isAxiosError: true,
  response: { status: 500, data: { error: { code: 'internal.server_error' } } },
};

function serverUp() {
  vi.mocked(getOverview).mockResolvedValue(overview);
  vi.mocked(listMachines).mockResolvedValue(empty as never);
  vi.mocked(listThreats).mockResolvedValue(empty);
}

function serverDown() {
  vi.mocked(getOverview).mockRejectedValue(fail500);
  vi.mocked(listMachines).mockRejectedValue(fail500);
  vi.mocked(listThreats).mockRejectedValue(fail500);
}

async function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'u',
    email: 'a@b.c',
    permissions: ['machine:read', 'threat:read'],
  } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: Stub },
      { path: '/machines', name: 'machines', component: Stub },
      { path: '/software', name: 'software', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push('/');
  const wrapper = mount(DashboardPage, {
    shallow: true,
    global: { plugins: [router, pinia], renderStubDefaultSlot: true },
  });
  await flushPromises();
  return wrapper;
}

async function clickReload(wrapper: Awaited<ReturnType<typeof mountPage>>) {
  await wrapper.find('[aria-label="Actualiser"]').trigger('click');
  await flushPromises();
}

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.mocked(getOverview).mockReset();
    vi.mocked(listMachines).mockReset();
    vi.mocked(listThreats).mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('says the parc is clean once its lists have loaded', async () => {
    serverUp();
    const w = await mountPage();

    expect(w.text()).toContain('Tous les postes sont à jour.');
    expect(w.text()).toContain('Aucune menace active.');
  });

  it('shows the banner when the very first load fails', async () => {
    serverDown();
    const w = await mountPage();

    expect(w.findComponent(LoadErrorBanner).exists()).toBe(true);
    expect(w.text()).not.toContain('Tous les postes sont à jour.');
  });

  // Audit U07: the empty messages follow the last load, not the first one.
  it('stops claiming « à jour » and « aucune menace » once a later load fails', async () => {
    serverUp();
    const w = await mountPage();
    serverDown();
    await clickReload(w);

    expect(w.text()).not.toContain('Tous les postes sont à jour.');
    expect(w.text()).not.toContain('Aucune menace active.');
  });

  it('keeps the threats’ empty message off when only the threats fail', async () => {
    serverUp();
    vi.mocked(listThreats).mockRejectedValue(fail500);
    const w = await mountPage();

    expect(w.text()).toContain('Tous les postes sont à jour.');
    expect(w.text()).not.toContain('Aucune menace active.');
  });

  // Audit T20: a requested reload over a page already shown says it failed.
  it('notifies when a requested reload fails over figures already shown', async () => {
    serverUp();
    const w = await mountPage();
    const notify = vi.spyOn(w.vm.$q, 'notify');
    serverDown();
    await clickReload(w);

    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'negative', message: expect.any(String) }),
    );
  });

  it('does not notify when a requested reload succeeds', async () => {
    serverUp();
    const w = await mountPage();
    const notify = vi.spyOn(w.vm.$q, 'notify');
    await clickReload(w);

    expect(notify).not.toHaveBeenCalled();
  });
});
