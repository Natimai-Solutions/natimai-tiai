import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  getMachineMaintenance: vi.fn(),
  updateMachineMaintenance: vi.fn(),
}));

import MaintenanceSettingsDialog from 'src/components/maintenance/MaintenanceSettingsDialog.vue';
import { tasksVersion } from 'src/composables/useTasksBadge';
import {
  getMachineMaintenance,
  updateMachineMaintenance,
  type MachineMaintenance,
  type MaintenanceSettingsPayload,
} from 'src/services/maintenance';
import MachineMaintenanceCard from './MachineMaintenanceCard.vue';

const info: MachineMaintenance = {
  maintenance_cycle_days: null,
  maintenance_owner: null,
  resolved: {
    cycle_days: 90,
    cycle_origin: 'global',
    owner: null,
    owner_origin: 'global',
    last_maintenance_at: null,
    // Mid-afternoon in Tahiti, the test's zone: a time is there to be dropped.
    due_at: '2026-12-03T01:47:12Z',
    state: 'ok',
  },
};

function mountCard() {
  return mount(MachineMaintenanceCard, {
    props: { machineId: 'm1', hostname: 'PC-01', canWrite: true },
  });
}

describe('MachineMaintenanceCard', () => {
  beforeEach(() => {
    vi.mocked(getMachineMaintenance).mockResolvedValue(info);
    vi.mocked(updateMachineMaintenance).mockResolvedValue(info);
  });

  // Audit U22: a deadline is a day, as « Mes tâches » writes it.
  it('gives the due date as a date, never to the second', async () => {
    const wrapper = mountCard();
    await flushPromises();

    expect(wrapper.text()).toContain('due le 02/12/2026');
    expect(wrapper.text()).not.toMatch(/\d{2}:\d{2}:\d{2}/);
  });

  // Audit U19: another owner or cycle changes « Mes tâches » for somebody.
  it('has the tasks badge read again once the settings are saved', async () => {
    const wrapper = mountCard();
    await flushPromises();
    const before = tasksVersion.value;

    const save = wrapper.findComponent(MaintenanceSettingsDialog).props('save') as (
      payload: MaintenanceSettingsPayload,
    ) => Promise<void>;
    await save({ maintenance_owner_id: 'u2' });

    expect(updateMachineMaintenance).toHaveBeenCalledWith('m1', { maintenance_owner_id: 'u2' });
    expect(tasksVersion.value).toBe(before + 1);
    expect(wrapper.emitted('changed')).toHaveLength(1);
  });
});
