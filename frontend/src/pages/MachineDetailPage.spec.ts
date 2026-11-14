import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QTabPanels } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

/**
 * The fiche against a fake server whose answers to `GET /machines/:id` are
 * held until the test releases them: the bugs here are all about which answer
 * lands when. Everything else the page asks for answers at once, empty.
 */
type Deferred = { resolve: (v: unknown) => void; reject: (e: unknown) => void };
const machineCalls: Record<string, Deferred[]> = {};
const calls: string[] = [];

vi.mock('boot/axios', () => {
  const page = { data: { items: [], total: 0 } };
  return {
    api: {
      get: vi.fn((url: string) => {
        calls.push(url);
        const m = /^\/machines\/([^/]+)$/.exec(url);
        if (m) {
          return new Promise((resolve, reject) => {
            (machineCalls[m[1]!] ??= []).push({ resolve, reject });
          });
        }
        if (url === '/threats' || url === '/commands' || url.endsWith('/interventions')) {
          return Promise.resolve(page);
        }
        if (url === '/rooms/config') return Promise.resolve({ data: { manual: true } });
        if (url.endsWith('/duplicates')) return Promise.resolve({ data: [] });
        return Promise.reject(new Error(`unexpected GET ${url}`));
      }),
      post: vi.fn(),
      patch: vi.fn(),
      put: vi.fn(),
      delete: vi.fn(),
    },
  };
});

import { api } from 'boot/axios';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import CheckRequestDialog from 'src/components/check/CheckRequestDialog.vue';
import MachineMergeDialog from 'src/components/machine/MachineMergeDialog.vue';
import { tasksVersion } from 'src/composables/useTasksBadge';
import type { CheckPayload } from 'src/services/checks';
import { useAuthStore } from 'src/stores/auth';
import MachineDetailPage from './MachineDetailPage.vue';

const Stub = defineComponent({ render: () => h('div') });

function detail(id: string) {
  return {
    id,
    machine_uuid: `uuid-${id}`,
    hostname: `HOST-${id}`,
    is_online: true,
    last_seen: new Date().toISOString(),
    software: [],
    disks: [],
  };
}

const fail500 = {
  isAxiosError: true,
  response: { status: 500, data: { error: { code: 'internal.server_error' } } },
};

function answer(id: string, n = 0) {
  machineCalls[id]![n]!.resolve({ data: detail(id) });
}

async function mountPage(id: string, permissions: string[], query = '') {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = { id: 'u', email: 'a@b.c', permissions } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/machines', name: 'machines', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push(`/machines/${id}${query}`);
  const wrapper = mount(MachineDetailPage, {
    shallow: true,
    props: { id },
    // Shallow for speed, but the page sits in a q-page: its content is the slot.
    global: { plugins: [router, pinia], renderStubDefaultSlot: true },
  });
  await flushPromises();
  return wrapper;
}

describe('MachineDetailPage', () => {
  beforeEach(() => {
    for (const k of Object.keys(machineCalls)) delete machineCalls[k];
    calls.length = 0;
  });

  // Audit T14: machine:read alone opens the fiche, and nothing it may not
  // read is asked for — a 403 there used to blank the whole page.
  it('asks neither for threats nor for commands with machine:read alone, and shows the poste', async () => {
    const w = await mountPage('B', ['machine:read']);
    answer('B');
    await flushPromises();

    expect(calls).not.toContain('/threats');
    expect(calls).not.toContain('/commands');
    expect(w.find('h1').text()).toContain('HOST-B');
    expect(w.findComponent(LoadErrorBanner).exists()).toBe(false);
  });

  it('falls back to the default tab when the commands tab is linked without command:read', async () => {
    const w = await mountPage('B', ['machine:read'], '?tab=commands');
    answer('B');
    await flushPromises();

    expect(w.findComponent(QTabPanels).props('modelValue')).toBe('identity');
  });

  it('keeps the commands tab for an account that may read commands', async () => {
    const w = await mountPage('B', ['machine:read', 'command:read'], '?tab=commands');
    answer('B');
    await flushPromises();

    expect(w.findComponent(QTabPanels).props('modelValue')).toBe('commands');
  });

  // Audit T20 (B04, U01): walking on before the previous poste has answered.
  it('never shows the poste being left under the next one’s id', async () => {
    const w = await mountPage('A', ['machine:read']);
    answer('A');
    await flushPromises();

    // Next: B is asked for...
    await w.setProps({ id: 'B' });
    await flushPromises();
    // ...and Next again before B has answered.
    await w.setProps({ id: 'C' });
    await flushPromises();
    answer('B');
    await flushPromises();

    // B's answer is dropped, C is asked for, and the page waits for it.
    expect(w.find('h1').text()).not.toContain('HOST-B');
    expect(machineCalls.C).toHaveLength(1);

    machineCalls.C![0]!.reject(fail500);
    await flushPromises();

    expect(w.find('h1').text()).not.toContain('HOST-B');
    expect(w.findComponent(LoadErrorBanner).exists()).toBe(true);
  });

  it('shows the next poste once it answers, after the dropped one', async () => {
    const w = await mountPage('A', ['machine:read']);
    answer('A');
    await flushPromises();
    await w.setProps({ id: 'B' });
    await w.setProps({ id: 'C' });
    await flushPromises();
    answer('B');
    await flushPromises();
    answer('C');
    await flushPromises();

    expect(w.find('h1').text()).toContain('HOST-C');
  });

  it('drops a refresh of the previous poste that answers after the walk', async () => {
    const w = await mountPage('A', ['machine:read']);
    answer('A');
    await flushPromises();
    // A refresh of A is in flight (the « Actualiser » button)...
    const refresh = w.findAll('[aria-label="Actualiser"]');
    expect(refresh).toHaveLength(1);
    await refresh[0]!.trigger('click');
    await flushPromises();
    expect(machineCalls.A).toHaveLength(2);
    // ...when the reader walks to B, which then fails.
    await w.setProps({ id: 'B' });
    await flushPromises();
    answer('A', 1);
    await flushPromises();
    machineCalls.B![0]!.reject(fail500);
    await flushPromises();

    expect(w.find('h1').text()).not.toContain('HOST-A');
    expect(w.findComponent(LoadErrorBanner).exists()).toBe(true);
  });

  // Audit B19: a merge writes the duplicate's history into this poste's journal.
  it('reloads the journal of interventions after a merge', async () => {
    const w = await mountPage('B', ['machine:read', 'machine:write', 'intervention:read']);
    answer('B');
    await flushPromises();
    const journal = () => calls.filter((u) => u === '/machines/B/interventions').length;
    expect(journal()).toBe(1);

    w.findComponent(MachineMergeDialog).vm.$emit('merged');
    await flushPromises();
    answer('B', 1);
    await flushPromises();

    expect(journal()).toBe(2);
  });

  // Audit U19: a check asked for from the fiche changes « Mes tâches ».
  it('has the tasks badge read again once a check is asked for', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} });
    const w = await mountPage('B', ['machine:read', 'check:write']);
    answer('B');
    await flushPromises();
    const before = tasksVersion.value;

    const ask = w.findAllComponents(CheckRequestDialog)[0]!.props('save') as (
      payload: CheckPayload,
    ) => Promise<void>;
    const done = ask({ assigned_to_id: null, instructions: 'Écran noir' });
    await flushPromises();
    answer('B', 1);
    await done;

    expect(api.post).toHaveBeenCalledWith('/machines/B/check', expect.anything());
    expect(tasksVersion.value).toBe(before + 1);
  });
});
