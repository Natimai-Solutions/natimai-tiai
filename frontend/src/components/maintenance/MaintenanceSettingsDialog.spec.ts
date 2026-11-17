import { flushPromises, mount } from '@vue/test-utils';
import { QSelect } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  listAssignableOwners: vi.fn(),
}));
vi.mock('src/services/checks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/checks')>()),
  listAssignableUsers: vi.fn(),
}));

import { listAssignableUsers } from 'src/services/checks';
import { listAssignableOwners } from 'src/services/maintenance';
import MaintenanceSettingsDialog from './MaintenanceSettingsDialog.vue';

function mountDialog(
  level: { machineId?: string; roomId?: string; ownerId?: string; ownerLabel?: string },
  save = vi.fn(),
) {
  return mount(MaintenanceSettingsDialog, {
    props: {
      modelValue: false,
      subject: 'PC-01',
      cycleDays: null,
      ownerId: null,
      inheritHint: 'Vide : hérite',
      save,
      ...level,
    },
    attachTo: document.body,
  });
}

/** The owner picker's choices, once the dialog is open. */
async function ownersOffered(wrapper: ReturnType<typeof mountDialog>) {
  await wrapper.setProps({ modelValue: true });
  await flushPromises();
  const picker = wrapper
    .findAllComponents(QSelect)
    .find((s) => s.props('label') === 'Responsable')!;
  return picker.props('options') as { label: string; value: string }[];
}

describe('MaintenanceSettingsDialog — who can be named owner', () => {
  beforeEach(() => {
    vi.mocked(listAssignableOwners).mockReset();
    vi.mocked(listAssignableUsers).mockReset();
    vi.mocked(listAssignableOwners).mockResolvedValue([{ id: 'u-1', name: 'Alice' }]);
    // Whoever may read a check: more accounts than the server accepts as owner.
    vi.mocked(listAssignableUsers).mockResolvedValue([
      { id: 'u-1', name: 'Alice' },
      { id: 'u-2', name: 'Bob' },
    ]);
  });

  it('offers the accounts the server accepts for the poste being set', async () => {
    const wrapper = mountDialog({ machineId: 'm-1' });

    expect(await ownersOffered(wrapper)).toEqual([{ label: 'Alice', value: 'u-1' }]);
    expect(listAssignableOwners).toHaveBeenCalledTimes(1);
    expect(vi.mocked(listAssignableOwners).mock.calls[0]![0]).toMatchObject({ machineId: 'm-1' });
    expect(vi.mocked(listAssignableOwners).mock.calls[0]![0]?.roomId ?? null).toBeNull();
    // Not the list of who may be given a check.
    expect(listAssignableUsers).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('offers the accounts the server accepts for the room being set', async () => {
    const wrapper = mountDialog({ roomId: 'r-1' });

    expect(await ownersOffered(wrapper)).toEqual([{ label: 'Alice', value: 'u-1' }]);
    expect(vi.mocked(listAssignableOwners).mock.calls[0]![0]).toMatchObject({ roomId: 'r-1' });
    expect(vi.mocked(listAssignableOwners).mock.calls[0]![0]?.machineId ?? null).toBeNull();
    expect(listAssignableUsers).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('asks nothing until it opens', async () => {
    const wrapper = mountDialog({ machineId: 'm-1' });
    await flushPromises();

    expect(listAssignableOwners).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});

describe('MaintenanceSettingsDialog — an owner deactivated since (item 4)', () => {
  beforeEach(() => {
    vi.mocked(listAssignableOwners).mockReset();
    vi.mocked(listAssignableOwners).mockResolvedValue([{ id: 'u-1', name: 'Alice' }]);
  });

  it('names the current owner instead of showing its id, and keeps it on save', async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const wrapper = mountDialog(
      { roomId: 'r-1', ownerId: 'u-gone', ownerLabel: 'Marie (désactivé)' },
      save,
    );
    expect(await ownersOffered(wrapper)).toEqual([
      { label: 'Marie (désactivé)', value: 'u-gone' },
      { label: 'Alice', value: 'u-1' },
    ]);
    wrapper.unmount();
  });
});
