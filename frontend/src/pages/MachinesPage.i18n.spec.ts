import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

// The list against a fake server: two postes, and the side lists the page
// asks for at mount answered empty or refused (they are best-effort).
vi.mock('boot/axios', () => ({
  api: {
    get: vi.fn((url: string) => {
      if (url === '/machines') {
        const base = {
          domain: 'LYCEE',
          location: 'Papeete',
          ip_address: '10.0.0.1',
          os_version: 'Windows 11 Pro',
          agent_version: '0.3.0',
          hw_model: 'OptiPlex 7010',
          room_name: 'B12',
          usage_hours: 12,
          system_volume_total_mb: 500_000,
          system_volume_free_mb: 250_000,
          last_seen: '2026-11-18T08:00:00Z',
          is_online: true,
        };
        return Promise.resolve({
          data: {
            items: [
              { ...base, id: 'a', hostname: 'PC-01', machine_uuid: 'a' },
              { ...base, id: 'b', hostname: 'PC-02', machine_uuid: 'b', usage_hours: null },
            ],
            total: 2,
            page: 1,
            page_size: 50,
            agent_latest_version: '0.3.0',
            usage_days: 7,
            usage_low_hours: 10,
            usage_high_hours: 50,
          },
        });
      }
      if (url === '/machines/models') {
        return Promise.resolve({ data: [{ name: 'OptiPlex 7010', count: 2 }] });
      }
      return Promise.reject(new Error(`unexpected GET ${url}`));
    }),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

import { setLocale } from 'src/i18n';
import { useAuthStore } from 'src/stores/auth';
import MachinesPage from './MachinesPage.vue';

/**
 * The machine list in English (plan `dev/plan-console-bilingue.md`, I6): the
 * toolbar, the search and filters, the table's headers and the cells it words
 * itself. The layout is narrowed to those columns: the badges of the others
 * (antivirus, updates, session, maintenance) are worded by the formatting
 * helpers, translated with their own pages.
 */

// Accented letters and French quotes: the data mounted here has none.
const FRENCH = /[éèàùçêô«»]/;

const Stub = defineComponent({ render: () => h('div') });

async function mountList() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'u',
    email: 'a@b.c',
    permissions: ['machine:read'],
    preferences: {
      machines_columns: [
        'hostname',
        'domain',
        'location',
        'room',
        'ip_address',
        'os_version',
        'agent',
        'usage',
        'model',
        'disk',
      ],
    },
  } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/machines', name: 'machines', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push('/machines?hw_model=OptiPlex%207010&ram_min_gb=16');
  const wrapper = mount(MachinesPage, {
    global: { plugins: [router, pinia], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  return wrapper;
}

afterEach(() => setLocale('fr'));

describe('MachinesPage in English', () => {
  it('shows the list with no French of its own', async () => {
    setLocale('en');
    const wrapper = await mountList();
    const text = wrapper.text();
    for (const expected of [
      'Computers',
      'Columns',
      'Export',
      'Switched on',
      'Active threats',
      'Filters',
      'OptiPlex 7010 (2)',
      'Memory ≥ 16 GiB',
      'Clear all',
      'Agent version',
      'Hours on (7 d)',
      'IP address',
      'recent',
    ]) {
      expect(text).toContain(expected);
    }
    expect(text).not.toMatch(FRENCH);
    for (const french of ['Postes', 'Colonnes', 'Filtres', 'Allumés', 'libres', 'Mémoire']) {
      expect(text).not.toContain(french);
    }
  });

  it('switches language live, without a reload', async () => {
    const wrapper = await mountList();
    expect(wrapper.text()).toContain('Version de l');
    expect(wrapper.text()).toContain('Mémoire ≥ 16 Gio');

    setLocale('en');
    await nextTick();

    const text = wrapper.text();
    expect(text).toContain('Agent version');
    expect(text).toContain('Memory ≥ 16 GiB');
    expect(text).toContain('Hours on (7 d)');
    expect(text).not.toMatch(FRENCH);
  });
});
