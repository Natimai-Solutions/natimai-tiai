import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QSelect } from 'quasar';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';

vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  recordSessionInParts: vi.fn(),
  getSession: vi.fn(),
  deleteSession: vi.fn(),
  listAssignableOwners: vi.fn(),
}));
vi.mock('src/composables/useTasksBadge', () => ({ notifyTasksChanged: vi.fn() }));

import { setLocale } from 'src/i18n';
import { getSession, listAssignableOwners, recordSessionInParts } from 'src/services/maintenance';
import { useAuthStore } from 'src/stores/auth';
import MaintenanceSessionDialog from './MaintenanceSessionDialog.vue';
import MaintenanceSessionViewDialog from './MaintenanceSessionViewDialog.vue';
import MaintenanceSettingsDialog from './MaintenanceSettingsDialog.vue';

const NO_FRENCH = /[éèàùç«»]|poste|Annuler|Enregistrer|Observation|Séance/;

function bodyText(): string {
  return document.body.textContent ?? '';
}

afterEach(() => {
  setLocale('fr');
  document.body.innerHTML = '';
});

describe('MaintenanceSessionDialog in English', () => {
  const machines = [
    { id: 'a', hostname: 'PC-A', hint: 'Overdue', preselect: true },
    { id: 'b', hostname: 'PC-B', preselect: true },
    { id: 'c', hostname: 'PC-C', preselect: false },
  ];

  async function open() {
    const wrapper = mount(MaintenanceSessionDialog, {
      props: { modelValue: false, roomId: 'r', roomName: 'B12', machines },
      attachTo: document.body,
    });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    return wrapper;
  }

  beforeEach(() => {
    vi.mocked(recordSessionInParts).mockReset();
  });

  it('reads in English, with no French left', async () => {
    setLocale('en');
    const wrapper = await open();
    const text = bodyText();

    expect(text).toContain('Maintenance — B12');
    expect(text).toContain('General note');
    expect(text).toContain('Backdating is allowed');
    expect(text).toContain('Computer');
    expect(text).toContain('Note on this computer');
    expect(text).toContain('Computers ticked: 2. Each gets a “Maintenance” line in its history');
    expect(text).toContain('Cancel');
    expect(text).toContain('Save');
    expect(document.querySelector('.q-dialog [aria-label="Note for PC-C"]')).not.toBeNull();
    expect(document.querySelector('.q-dialog [aria-label="Tick or untick all"]')).not.toBeNull();
    expect(text).not.toMatch(NO_FRENCH);
    wrapper.unmount();
  });

  it('says where a sending stopped, in English', async () => {
    vi.mocked(recordSessionInParts).mockRejectedValue(new Error('offline'));
    setLocale('en');
    const wrapper = await open();
    const notify = vi.spyOn(wrapper.vm.$q, 'notify').mockImplementation(() => () => undefined);

    document
      .querySelector('.q-dialog form')!
      .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await flushPromises();

    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'negative', message: 'Could not save' }),
    );
    expect(bodyText()).toContain('Sending stopped without an answer from the server');
    expect(bodyText()).toContain('Resume sending');
    wrapper.unmount();
  });

  it('notifies a recorded visit in English', async () => {
    vi.mocked(recordSessionInParts).mockResolvedValue({} as never);
    setLocale('en');
    const wrapper = await open();
    const notify = vi.spyOn(wrapper.vm.$q, 'notify').mockImplementation(() => () => undefined);

    document
      .querySelector('.q-dialog form')!
      .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    await flushPromises();

    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'positive',
        message: 'Maintenance recorded on 2 computers',
      }),
    );
    wrapper.unmount();
  });

  it('switches language live, the hints the page passes included', async () => {
    const wrapper = await open();
    expect(bodyText()).toContain('Observation générale');

    setLocale('en');
    await wrapper.setProps({ machines: machines.map((m) => ({ ...m })) });
    await nextTick();

    expect(bodyText()).toContain('General note');
    expect(bodyText()).toContain('Overdue');
    expect(bodyText()).not.toContain('Observation générale');
    wrapper.unmount();
  });
});

describe('MaintenanceSessionViewDialog in English', () => {
  beforeEach(() => {
    vi.mocked(getSession).mockResolvedValue({
      id: 's-1',
      room_id: 'r-1',
      room_name: 'A101',
      performed_by: 'alice@test.local',
      performed_at: '2026-11-10T20:00:00Z',
      note: null,
      machine_count: 1,
      items: [{ intervention_id: 'i-1', machine_id: 'm-1', hostname: 'PC-01', note: 'Dusted' }],
      skipped: [{ intervention_id: 'i-2', machine_id: 'm-2', hostname: 'PC-02', note: 'Absent' }],
      partial: true,
    });
  });

  it('reads in English, with no French left', async () => {
    setActivePinia(createPinia());
    useAuthStore().user = {
      id: 'me',
      email: 'a@b.c',
      permissions: ['maintenance:read', 'maintenance:write'],
    } as never;
    setLocale('en');
    const wrapper = mount(MaintenanceSessionViewDialog, {
      props: { modelValue: false, sessionId: 's-1' },
      attachTo: document.body,
    });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    const text = bodyText();

    expect(text).toContain('Maintenance session — A101');
    expect(text).toContain(
      'This session goes beyond your scope: only your computers are shown, without the general note.',
    );
    expect(text).toContain('By');
    expect(text).toContain('Computers done (1)');
    expect(text).toContain('Computers not done');
    expect(text).toContain('Close');
    expect(text).not.toMatch(NO_FRENCH);
    wrapper.unmount();
  });
});

describe('MaintenanceSettingsDialog in English', () => {
  beforeEach(() => {
    vi.mocked(listAssignableOwners)
      .mockReset()
      .mockResolvedValue([{ id: 'u-1', name: 'Alice' }]);
  });

  function mountDialog() {
    return mount(MaintenanceSettingsDialog, {
      props: {
        modelValue: false,
        subject: 'PC-01',
        cycleDays: 30,
        ownerId: 'u-9',
        roomId: 'r-1',
        inheritHint: 'Empty: the default',
        save: vi.fn(),
      },
      attachTo: document.body,
    });
  }

  it('reads in English, the cycle modes and the unreachable owner included', async () => {
    setLocale('en');
    const wrapper = mountDialog();
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    const text = bodyText();

    expect(text).toContain('Maintenance — PC-01');
    expect(text).toContain('Every');
    expect(text).toContain('days');
    const [cycle, owner] = wrapper.findAllComponents(QSelect);
    expect(cycle!.props('label')).toBe('Cycle');
    expect(cycle!.props('options')).toEqual([
      { label: 'Inherit (room, then fleet)', value: 'inherit' },
      { label: 'Own cycle', value: 'custom' },
      { label: 'Exclude from maintenance', value: 'excluded' },
    ]);
    expect(owner!.props('label')).toBe('Owner');
    expect(owner!.props('options')).toEqual([
      { label: 'Account deactivated or out of reach', value: 'u-9' },
      { label: 'Alice', value: 'u-1' },
    ]);
    expect(text).not.toMatch(NO_FRENCH);
    wrapper.unmount();
  });

  it('switches language live', async () => {
    const wrapper = mountDialog();
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    expect(wrapper.findAllComponents(QSelect)[1]!.props('label')).toBe('Responsable');

    setLocale('en');
    await nextTick();

    expect(wrapper.findAllComponents(QSelect)[1]!.props('label')).toBe('Owner');
    expect(bodyText()).toContain('Every');
    wrapper.unmount();
  });
});
