import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QBtn } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  getSession: vi.fn(),
  deleteSession: vi.fn(),
}));

import { tasksVersion } from 'src/composables/useTasksBadge';
import { deleteSession, getSession } from 'src/services/maintenance';
import { useAuthStore } from 'src/stores/auth';
import MaintenanceSessionViewDialog from './MaintenanceSessionViewDialog.vue';

async function open(permissions: string[]) {
  setActivePinia(createPinia());
  useAuthStore().user = { id: 'me', email: 'a@b.c', permissions } as never;
  const wrapper = mount(MaintenanceSessionViewDialog, {
    props: { modelValue: false, sessionId: 's-1' },
    attachTo: document.body,
  });
  await wrapper.setProps({ modelValue: true });
  await flushPromises();
  return wrapper;
}

describe('MaintenanceSessionViewDialog (item 6)', () => {
  beforeEach(() => {
    vi.mocked(deleteSession).mockReset();
    vi.mocked(getSession).mockResolvedValue({
      id: 's-1',
      room_id: 'r-1',
      room_name: 'A101',
      performed_by: 'alice@test.local',
      performed_at: '2026-11-10T20:00:00Z',
      note: 'Observation générale',
      machine_count: 0,
      items: [],
      skipped: [],
    });
  });

  it('deletes the visit only once confirmed', async () => {
    vi.mocked(deleteSession).mockResolvedValue(undefined);
    const wrapper = await open(['maintenance:read', 'maintenance:write']);
    expect(document.body.textContent).toContain('Aucun poste ne garde de ligne');
    let confirm: (() => void) | null = null;
    const dialog = vi.spyOn(wrapper.vm.$q, 'dialog').mockImplementation((() => ({
      onOk(fn: () => void) {
        confirm = fn;
        return this;
      },
    })) as never);
    const before = tasksVersion.value;
    const button = wrapper
      .findAllComponents(QBtn)
      .find((b) => b.text().includes('Supprimer la séance'))!;
    await button.trigger('click');
    await flushPromises();

    expect(dialog).toHaveBeenCalledTimes(1);
    expect(deleteSession).not.toHaveBeenCalled();
    confirm!();
    await flushPromises();

    expect(deleteSession).toHaveBeenCalledWith('s-1');
    expect(wrapper.emitted('deleted')).toHaveLength(1);
    expect(tasksVersion.value).toBe(before + 1);
    wrapper.unmount();
  });

  it('offers no deletion without maintenance:write', async () => {
    const wrapper = await open(['maintenance:read']);
    expect(wrapper.findAllComponents(QBtn).some((b) => b.text().includes('Supprimer'))).toBe(false);
    wrapper.unmount();
  });
});
