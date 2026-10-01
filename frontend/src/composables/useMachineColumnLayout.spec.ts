// @vitest-environment jsdom
// The auth store reads its token from localStorage as it is created, which
// node does not have — the one reason this spec wants a DOM.
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick, ref } from 'vue';

const q = vi.hoisted(() => ({ notify: vi.fn() }));
vi.mock('quasar', () => ({ useQuasar: () => q }));
vi.mock('src/services/auth', () => ({ getMe: vi.fn(), login: vi.fn(), updateMe: vi.fn() }));

import { updateMe, type User } from 'src/services/auth';
import { useAuthStore } from 'src/stores/auth';
import { DEFAULT_MACHINE_COLUMNS } from 'src/utils/machineColumns';
import { useMachineColumnLayout } from './useMachineColumnLayout';

function user(preferences: Record<string, unknown> = {}): User {
  return { id: 'u-1', email: 'a@b.c', permissions: [], preferences } as unknown as User;
}

describe('useMachineColumnLayout', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('starts on the default layout until the profile says otherwise', async () => {
    const { columnOrder } = useMachineColumnLayout(ref(7));
    expect(columnOrder.value).toEqual(DEFAULT_MACHINE_COLUMNS);

    // The profile may arrive after the page: a reload restores it in the layout.
    useAuthStore().user = user({ machines_columns: ['hostname', 'usage'] });
    await nextTick();

    expect(columnOrder.value).toEqual(['hostname', 'usage']);
  });

  it('names the usage window the server answered with in the header', async () => {
    useAuthStore().user = user({ machines_columns: ['hostname', 'usage'] });
    const days = ref(7);
    const { visibleColumns } = useMachineColumnLayout(days);
    expect(visibleColumns.value[1]!.label).toBe('Allumé (7 j)');

    days.value = 28;
    await nextTick();

    expect(visibleColumns.value[1]!.label).toBe('Allumé (28 j)');
  });

  it('stores a layout on the account, and the default as an absence', async () => {
    vi.mocked(updateMe).mockResolvedValue(user());
    const { columnOrder, saveColumns } = useMachineColumnLayout(ref(7));

    await saveColumns(['hostname', 'disk']);
    expect(updateMe).toHaveBeenLastCalledWith({
      preferences: { machines_columns: ['hostname', 'disk'] },
    });
    expect(columnOrder.value).toEqual(['hostname', 'disk']);

    await saveColumns([...DEFAULT_MACHINE_COLUMNS]);
    expect(updateMe).toHaveBeenLastCalledWith({ preferences: { machines_columns: null } });
  });

  it('says a failure and rethrows it, so the dialog stays open', async () => {
    vi.mocked(updateMe).mockRejectedValue(new Error('down'));
    const { columnOrder, saveColumns } = useMachineColumnLayout(ref(7));

    await expect(saveColumns(['hostname'])).rejects.toThrow('down');

    expect(q.notify).toHaveBeenCalledWith({
      type: 'negative',
      message: "Impossible d'enregistrer les colonnes",
    });
    expect(columnOrder.value).toEqual(DEFAULT_MACHINE_COLUMNS);
  });
});
