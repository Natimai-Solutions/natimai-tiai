import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';

vi.mock('src/services/interventions', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/interventions')>()),
  createIntervention: vi.fn(),
  updateIntervention: vi.fn(),
  deleteIntervention: vi.fn(),
}));
vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  getSession: vi.fn(),
  getMachineMaintenance: vi.fn(),
  updateMachineMaintenance: vi.fn(),
}));

import MaintenanceSettingsDialog from 'src/components/maintenance/MaintenanceSettingsDialog.vue';
import { setLocale } from 'src/i18n';
import { updateIntervention, type Intervention } from 'src/services/interventions';
import { getMachineMaintenance, type MachineMaintenance } from 'src/services/maintenance';
import { useAuthStore } from 'src/stores/auth';
import MachineHistoryCard from './MachineHistoryCard.vue';
import MachineMaintenanceCard from './MachineMaintenanceCard.vue';

const at = '2026-11-10T20:00:00Z';
const line = (fields: Partial<Intervention>): Intervention => ({
  id: 'i',
  machine_id: 'm1',
  kind: 'other',
  title: null,
  note: null,
  performed_by: 'Alice',
  performed_at: at,
  created_at: at,
  updated_at: at,
  ...fields,
});

const items: Intervention[] = [
  line({ id: 'i1', kind: 'maintenance', title: 'A101', maintenance_id: 's-1' }),
  // Written by the server under a code: worded by the console.
  line({
    id: 'i2',
    kind: 'other',
    title: 'Maintenance non faite — B12',
    title_code: 'maintenance.skipped',
    title_params: { room: 'B12' },
    note: 'Absent',
  }),
  // Written before the codes, in French: its kind is not repeated.
  line({
    id: 'i3',
    kind: 'verification',
    title: 'Vérification',
    updated_at: '2026-11-11T08:00:00Z',
  }),
];

function mountHistory() {
  setActivePinia(createPinia());
  useAuthStore().user = {
    id: 'me',
    email: 'a@b.c',
    permissions: ['maintenance:read'],
  } as never;
  return mount(MachineHistoryCard, {
    props: { machineId: 'm1', items, total: 5, loading: false, canWrite: true },
    attachTo: document.body,
  });
}

afterEach(() => {
  setLocale('fr');
  document.body.innerHTML = '';
});

describe('MachineHistoryCard in English', () => {
  beforeEach(() => {
    vi.mocked(updateIntervention)
      .mockReset()
      .mockResolvedValue({} as never);
  });

  it('reads in English, the titles the server wrote included', async () => {
    setLocale('en');
    const wrapper = mountHistory();
    await flushPromises();
    const text = wrapper.text();

    expect(text).toContain('Intervention log');
    expect(text).toContain('Add an intervention');
    expect(text).toContain('Maintenance — A101');
    expect(text).toContain('Other — Maintenance not done — B12');
    expect(text).toContain('Check');
    expect(text).toContain('edited');
    expect(text).toContain('View the session');
    expect(text).toContain('Show more');
    expect(text).not.toMatch(/[éèàùç«»]|Vérification|Autre|non faite|Afficher/);
    wrapper.unmount();
  });

  it('keeps the code of a title left as shown, and drops it once retyped', async () => {
    setLocale('en');
    const wrapper = mountHistory();
    await flushPromises();

    async function edit(index: number) {
      await wrapper.findAll('[aria-label="Actions on the intervention"]')[index]!.trigger('click');
      await flushPromises();
      const item = [...document.querySelectorAll<HTMLElement>('.q-menu .q-item')].find((i) =>
        i.textContent?.includes('Edit'),
      )!;
      item.click();
      await flushPromises();
    }
    function submit() {
      document
        .querySelector('.q-dialog form')!
        .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      return flushPromises();
    }

    await edit(1);
    expect(document.body.textContent).toContain('Edit the intervention');
    const title = document.querySelector<HTMLInputElement>('.q-dialog input[maxlength="200"]')!;
    expect(title.value).toBe('Maintenance not done — B12');
    await submit();
    expect(vi.mocked(updateIntervention).mock.calls[0]![1]).not.toHaveProperty('title');

    await edit(1);
    const retyped = document.querySelector<HTMLInputElement>('.q-dialog input[maxlength="200"]')!;
    retyped.value = 'Skipped: off';
    retyped.dispatchEvent(new Event('input'));
    await flushPromises();
    await submit();
    expect(vi.mocked(updateIntervention).mock.calls[1]![1]).toMatchObject({
      title: 'Skipped: off',
    });
    wrapper.unmount();
  });

  it('switches language live', async () => {
    const wrapper = mountHistory();
    await flushPromises();
    expect(wrapper.text()).toContain('Autre — Maintenance non faite — B12');

    setLocale('en');
    await nextTick();

    expect(wrapper.text()).toContain('Other — Maintenance not done — B12');
    expect(wrapper.text()).toContain('Intervention log');
    wrapper.unmount();
  });
});

describe('MachineMaintenanceCard in English', () => {
  const info: MachineMaintenance = {
    maintenance_cycle_days: null,
    maintenance_owner: null,
    resolved: {
      cycle_days: 90,
      cycle_origin: 'room',
      owner: { id: 'u-1', name: 'Mary' },
      owner_origin: 'global',
      last_maintenance_at: null,
      due_at: '2026-12-10T12:00:00Z',
      state: 'overdue',
    },
  };

  beforeEach(() => {
    vi.mocked(getMachineMaintenance).mockResolvedValue(info);
  });

  it('reads in English, with no French left', async () => {
    setLocale('en');
    const wrapper = mount(MachineMaintenanceCard, {
      props: { machineId: 'm1', hostname: 'PC-01', canWrite: true },
    });
    await flushPromises();
    const text = wrapper.text();

    expect(text).toContain('Maintenance');
    expect(text).toContain('Adjust');
    expect(text).toContain('Record a maintenance');
    expect(text).toContain('State');
    expect(text).toContain('Overdue');
    expect(text).toMatch(/due on \d{2}\/\d{2}\/2026/);
    expect(text).toContain('90 days (from the room)');
    expect(text).toContain('Mary');
    expect(text).toContain('(fleet default)');
    expect(text).toContain('Last maintenance');
    expect(text).toContain('never');
    expect(wrapper.findComponent(MaintenanceSettingsDialog).props('inheritHint')).toBe(
      'Empty: inherits from the room, then the fleet',
    );
    expect(text).not.toMatch(/[éèàùç«»]|Responsable|jamais|jours/);
    wrapper.unmount();
  });

  it('switches language live', async () => {
    const wrapper = mount(MachineMaintenanceCard, {
      props: { machineId: 'm1', hostname: 'PC-01', canWrite: true },
    });
    await flushPromises();
    expect(wrapper.text()).toContain('90 jours (hérité de la salle)');

    setLocale('en');
    await nextTick();

    expect(wrapper.text()).toContain('90 days (from the room)');
    wrapper.unmount();
  });
});
