import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  getMachineMaintenance: vi.fn(),
  updateMachineMaintenance: vi.fn(),
}));

import { QBtn } from 'quasar';
import CardLoadError from 'src/components/CardLoadError.vue';
import MaintenanceSettingsDialog from 'src/components/maintenance/MaintenanceSettingsDialog.vue';
import { notifyTasksChanged, tasksVersion } from 'src/composables/useTasksBadge';
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

  it('has the settings dialog offer the owners the server accepts for this poste', async () => {
    const wrapper = mountCard();
    await flushPromises();

    const dialog = wrapper.findComponent(MaintenanceSettingsDialog);
    expect(dialog.props('machineId')).toBe('m1');
    expect(dialog.props('roomId')).toBeUndefined();
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

describe('MachineMaintenanceCard — after a change to the journal (item 10)', () => {
  beforeEach(() => {
    vi.mocked(getMachineMaintenance).mockReset();
    vi.mocked(getMachineMaintenance).mockResolvedValue(info);
  });

  it('reads the maintenance again when a line is added, edited or deleted', async () => {
    const wrapper = mountCard();
    await flushPromises();
    expect(wrapper.text()).toContain('jamais');
    // Cards mounted by earlier tests listen too: count from here.
    const before = vi.mocked(getMachineMaintenance).mock.calls.length;
    vi.mocked(getMachineMaintenance).mockResolvedValue({
      ...info,
      resolved: { ...info.resolved, last_maintenance_at: '2026-11-10T20:00:00Z' },
    });

    // What the history card does after any save or delete.
    notifyTasksChanged();
    await flushPromises();

    expect(vi.mocked(getMachineMaintenance).mock.calls.length).toBeGreaterThan(before);
    expect(wrapper.text()).not.toContain('jamais');
    wrapper.unmount();
  });

  it('names a deactivated owner to the settings dialog (item 4)', async () => {
    vi.mocked(getMachineMaintenance).mockResolvedValue({
      ...info,
      maintenance_owner: { id: 'u-gone', name: 'Marie', active: false },
    });
    const wrapper = mountCard();
    await flushPromises();
    expect(wrapper.findComponent(MaintenanceSettingsDialog).props('ownerLabel')).toBe(
      'Marie (désactivé)',
    );
    wrapper.unmount();
  });
});

// Review finding 4: a read that failed left the card blank, with no retry —
// and « Régler » open on empty fields that saving would have written.
describe('MachineMaintenanceCard — a read that fails', () => {
  beforeEach(() => {
    vi.mocked(getMachineMaintenance).mockReset();
  });

  it('says so with « Réessayer », and shows the maintenance once it answers', async () => {
    vi.mocked(getMachineMaintenance).mockRejectedValueOnce({ response: { status: 500 } });
    const wrapper = mountCard();
    await flushPromises();
    const error = wrapper.findComponent(CardLoadError);
    expect(error.text()).toContain('Impossible de charger la maintenance de ce poste.');
    expect(wrapper.text()).not.toContain('Régler');

    vi.mocked(getMachineMaintenance).mockResolvedValue(info);
    await error.findComponent(QBtn).trigger('click');
    await flushPromises();
    expect(wrapper.findComponent(CardLoadError).exists()).toBe(false);
    expect(wrapper.text()).toContain('due le 02/12/2026');
    expect(wrapper.text()).toContain('Régler');
    wrapper.unmount();
  });

  it('keeps what it showed when a later read fails, and says it could not read', async () => {
    vi.mocked(getMachineMaintenance).mockResolvedValueOnce(info);
    const wrapper = mountCard();
    await flushPromises();
    vi.mocked(getMachineMaintenance).mockRejectedValue({ response: { status: 500 } });
    notifyTasksChanged();
    await flushPromises();
    expect(wrapper.findComponent(CardLoadError).exists()).toBe(true);
    expect(wrapper.text()).toContain('due le 02/12/2026');
    wrapper.unmount();
  });

  it('forgets the maintenance of the poste left when the next one cannot be read', async () => {
    vi.mocked(getMachineMaintenance).mockResolvedValueOnce(info);
    const wrapper = mountCard();
    await flushPromises();
    vi.mocked(getMachineMaintenance).mockRejectedValue({ response: { status: 500 } });
    await wrapper.setProps({ machineId: 'm2' });
    await flushPromises();
    expect(wrapper.findComponent(CardLoadError).exists()).toBe(true);
    expect(wrapper.text()).not.toContain('due le 02/12/2026');
    wrapper.unmount();
  });
});
