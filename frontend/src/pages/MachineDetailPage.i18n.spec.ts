import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

/**
 * The computer's page in English (plan console bilingue, lot A), against a
 * fake server answering at once. The cards of other batches (history,
 * maintenance, commands, the deploy and check dialogs) are stubbed: their
 * English is theirs to test.
 */

const DAY = 86_400_000;
const ago = (days: number) => new Date(Date.now() - days * DAY).toISOString();

vi.mock('boot/axios', () => {
  const page = { data: { items: [], total: 0 } };
  return {
    api: {
      get: vi.fn((url: string) => {
        if (url === '/machines/m1') return Promise.resolve({ data: computer() });
        if (url === '/machines/m1/neighbours') {
          return Promise.resolve({
            data: {
              previous: { id: 'm0', machine_uuid: 'uuid-0', hostname: 'PC-LAB-00', cursor: 'a' },
              next: { id: 'm2', machine_uuid: 'uuid-2', hostname: 'PC-LAB-02', cursor: 'b' },
              rank: 5,
              total: 340,
              cursor: 'c',
            },
          });
        }
        if (url === '/machines/m1/duplicates') return Promise.resolve({ data: [{}, {}] });
        if (url === '/threats' || url === '/commands') return Promise.resolve(page);
        if (url.endsWith('/interventions')) return Promise.resolve(page);
        if (url === '/stats/overview') return Promise.resolve({ data: {} });
        return Promise.reject(new Error(`unexpected GET ${url}`));
      }),
      post: vi.fn(),
      patch: vi.fn(),
      put: vi.fn(),
      delete: vi.fn(),
    },
  };
});

vi.mock('src/services/rooms', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/rooms')>()),
  getRoomConfig: vi.fn(() => Promise.resolve({ manual: true })),
}));

import { machineDetail } from 'src/test/fixtures';
import { setLocale } from 'src/i18n';
import machineCatalogue from 'src/i18n/messages/machine';
import { useAuthStore } from 'src/stores/auth';
import MachineDetailPage from './MachineDetailPage.vue';

/** A computer with every banner of the page up, its data accent-free. */
function computer() {
  return machineDetail({
    id: 'm1',
    hostname: 'PC-LAB-01',
    needs_verification: true,
    reenroll_requested_at: ago(1),
    reenroll_requested_ip: '10.0.0.9',
    location: 'Building A',
    room_id: 'r1',
    room_name: 'Lab 1',
    room_location: 'Building B',
    location_mismatch: true,
    check_open: true,
    open_check: {
      id: 'c1',
      requested_by: 'Marie',
      assigned_to_id: 'u2',
      assigned_to_name: 'Paul',
      assignee_reachable: false,
      instructions: 'Look at the screen',
      created_at: ago(0),
    },
  });
}

const Stub = defineComponent({ render: () => h('div') });
// Other batches' components: stubbed, so this page's own English is what is read.
const stubs = {
  MachineHistoryCard: true,
  MachineMaintenanceCard: true,
  MachineCommandsCard: true,
  CommandOutputDialog: true,
  PackageDeployDialog: true,
  CheckRequestDialog: true,
  CheckCloseDialog: true,
  MachineUsageCard: true,
  MachineStatusCard: true,
  MachineIdentityCard: true,
  MachineNetworkCard: true,
};

async function mountPage() {
  // The tabs are real, their labels being under test: q-tabs measures itself
  // with a ResizeObserver, which jsdom has not.
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'u',
    email: 'a@b.c',
    permissions: [
      'machine:read',
      'machine:write',
      'check:write',
      'room:read',
      'room:write',
      'threat:read',
      'command:read',
      'command:execute',
      'intervention:read',
    ],
  } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/machines', name: 'machines', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push('/machines/m1?i=5');
  const wrapper = mount(MachineDetailPage, {
    props: { id: 'm1' },
    global: {
      plugins: [router, pinia],
      stubs: { ...stubs, QPage: { template: '<div><slot /></div>' } },
    },
  });
  await flushPromises();
  return wrapper;
}

/** Every leaf of a catalogue. */
function leaves(tree: object): string[] {
  return Object.values(tree).flatMap((v) => (typeof v === 'string' ? [v] : leaves(v as object)));
}

/**
 * The French of this page's catalogue, as the fragments between placeholders
 * that English does not share: none may show on the English page.
 */
const FRENCH = (() => {
  const fragments = (texts: string[]) =>
    texts.flatMap((s) => s.split(/\{[^}]*\}| \| /).map((f) => f.trim()));
  const english = new Set(fragments(leaves(machineCatalogue.en)));
  return [...new Set(fragments(leaves(machineCatalogue.fr)))].filter(
    // Several words, or an accent: a single plain word (« Action ») may sit inside English.
    (f) => f.length >= 6 && (f.includes(' ') || /[^\x00-\x7f]/.test(f)) && !english.has(f),
  );
})();

afterEach(() => setLocale('fr'));

describe('MachineDetailPage — English', () => {
  it('shows the header, the banners and the tabs in English', async () => {
    setLocale('en');
    const w = await mountPage();
    const text = w.text();

    expect(w.find('h1').text()).toContain('PC-LAB-01');
    expect(text).toContain('Computer 6 of 340');
    expect(text).toContain('Refreshed at');
    expect(w.find('[aria-label="Previous computer"]').exists()).toBe(true);
    expect(w.find('[aria-label="Back to the computer list"]').exists()).toBe(true);
    for (const label of ['Actions', 'Change room', 'Merge (2)', 'Revoke the token']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Re-enrolment requested on');
    expect(text).toContain('from 10.0.0.9, while this computer still has a valid token.');
    expect(text).toContain('Fingerprint mismatch: this computer needs a manual check');
    expect(text).toContain('Check requested');
    expect(text).toContain(
      'to be picked up (Paul, who it was assigned to, can no longer see this computer).',
    );
    expect(text).toContain(
      'Location mismatch: the agent reports “Building A”, but room Lab 1 is at “Building B”.',
    );
    for (const tab of [
      'Identity',
      'Antivirus',
      'Windows Update',
      'Hardware',
      'Software',
      'Commands',
      'History',
    ]) {
      expect(text, tab).toContain(tab);
    }
    for (const french of FRENCH) expect(text, french).not.toContain(french);
  });

  it('asks its confirmations in English', async () => {
    setLocale('en');
    const w = await mountPage();
    const dialog = vi.spyOn(w.vm.$q, 'dialog').mockReturnValue({ onOk: () => undefined } as never);
    const button = w.findAll('button').find((b) => b.text().includes('Revoke the token'))!;
    await button.trigger('click');
    expect(dialog).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Revoke the token',
        message: expect.stringContaining('The computer will be cut off from the server'),
        cancel: expect.objectContaining({ label: 'Cancel' }),
        ok: expect.objectContaining({ label: 'Revoke' }),
      }),
    );
  });

  it('switches language live', async () => {
    const w = await mountPage();
    expect(w.text()).toContain('Changer de salle');
    expect(w.text()).toContain('Poste 6 sur 340');

    setLocale('en');
    await nextTick();
    expect(w.text()).toContain('Change room');
    expect(w.text()).toContain('Computer 6 of 340');
    expect(w.text()).not.toContain('Changer de salle');
  });
});
